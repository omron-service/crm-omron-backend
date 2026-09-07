import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import desc
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from app.db.session import get_db
from app.core.deps import get_current_user, require_department_access
from app.models.schema import PartCatalog, PartStock, PartStockMovement, PartStockOpname, User
from app.services.excel_export import generate_inventory_excel

logger = logging.getLogger("uvicorn.error")

router = APIRouter(prefix="/api/v1/inventory-parts", tags=["Inventory Part"])

VALID_INV_LOCATIONS = ("pusat", "cabang")

# Jenis pergerakan yang boleh dilakukan di masing-masing lokasi, dan arahnya
# (+1 = menambah stok / item masuk, -1 = mengurangi stok / item keluar)
MOVEMENT_RULES = {
    "pusat": {
        "terima_gudang": 1,        # Terima sparepart dari Gudang (item masuk)
        "kirim_ke_cabang": -1,     # Kirim sparepart ke Cabang (item keluar)
        "terima_dari_cabang": 1,   # Terima sparepart dari Cabang (item masuk)
        "terpakai_pusat": -1,      # Terpakai sparepart di Pusat (item keluar)
    },
    "cabang": {
        "terima_dari_pusat": 1,      # Terima sparepart dari Pusat (item masuk)
        "kirim_balik_ke_pusat": -1,  # Kirim balik sparepart ke Pusat (item keluar)
        "terpakai_cabang": -1,       # Terpakai sparepart di Cabang (item keluar)
    },
}

MOVEMENT_LABELS = {
    "terima_gudang": "Terima dari Gudang",
    "kirim_ke_cabang": "Kirim ke Cabang",
    "terima_dari_cabang": "Terima dari Cabang",
    "terpakai_pusat": "Terpakai di Pusat",
    "terima_dari_pusat": "Terima dari Pusat",
    "kirim_balik_ke_pusat": "Kirim Balik ke Pusat",
    "terpakai_cabang": "Terpakai di Cabang",
}


class MovementIn(BaseModel):
    location: str
    movement_type: str
    code: str
    name: Optional[str] = None
    quantity: int = Field(..., gt=0)
    note: Optional[str] = None


class OpnameIn(BaseModel):
    location: str
    code: str
    name: Optional[str] = None
    counted_quantity: int = Field(..., ge=0)
    note: Optional[str] = None


def _get_or_create_part(db: Session, code: str, name: Optional[str]) -> PartCatalog:
    part = db.query(PartCatalog).filter(PartCatalog.code == code).first()
    if part is None:
        part = PartCatalog(code=code, name=name)
        db.add(part)
        db.flush()
    elif name and part.name != name:
        part.name = name  # nama boleh diperbarui, kode tetap jadi kunci
    return part


def _get_or_create_stock_row(db: Session, part_id: int, location: str) -> PartStock:
    stock = (
        db.query(PartStock)
        .filter(PartStock.part_id == part_id, PartStock.location == location)
        .with_for_update()
        .first()
    )
    if stock is None:
        stock = PartStock(part_id=part_id, location=location, quantity=0)
        db.add(stock)
        db.flush()
    return stock


@router.get("/stock/{location}")
def get_stock_list(
    location: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    loc = location.lower().strip()
    if loc not in VALID_INV_LOCATIONS:
        raise HTTPException(status_code=400, detail=f"location harus salah satu dari: {', '.join(VALID_INV_LOCATIONS)}.")
    require_department_access(current_user, loc)

    rows = (
        db.query(PartStock, PartCatalog)
        .join(PartCatalog, PartStock.part_id == PartCatalog.id)
        .filter(PartStock.location == loc)
        .order_by(PartCatalog.name)
        .all()
    )
    return [
        {
            "part_id": part.id,
            "code": part.code,
            "name": part.name,
            "unit_price": part.unit_price,
            "quantity": stock.quantity,
            "updated_at": stock.updated_at,
        }
        for stock, part in rows
    ]


@router.post("/movement")
def create_movement(
    data: MovementIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    loc = data.location.lower().strip()
    if loc not in VALID_INV_LOCATIONS:
        raise HTTPException(status_code=400, detail=f"location harus salah satu dari: {', '.join(VALID_INV_LOCATIONS)}.")
    require_department_access(current_user, loc)

    allowed = MOVEMENT_RULES.get(loc, {})
    if data.movement_type not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"movement_type '{data.movement_type}' tidak berlaku untuk lokasi '{loc}'. "
                   f"Pilihan yang valid: {', '.join(allowed.keys())}.",
        )

    direction = allowed[data.movement_type]  # +1 atau -1

    try:
        part = _get_or_create_part(db, data.code.strip(), data.name)
        stock = _get_or_create_stock_row(db, part.id, loc)

        new_quantity = stock.quantity + (direction * data.quantity)
        if new_quantity < 0:
            raise HTTPException(
                status_code=400,
                detail=f"Stok tidak mencukupi. Stok saat ini {stock.quantity}, "
                       f"tidak bisa mengurangi {data.quantity}.",
            )

        stock.quantity = new_quantity
        db.add(PartStockMovement(
            part_id=part.id,
            location=loc,
            movement_type=data.movement_type,
            quantity=data.quantity,
            note=data.note,
            performed_by_user_id=current_user.id,
        ))
        db.commit()
        return {
            "status": "success",
            "code": part.code,
            "name": part.name,
            "location": loc,
            "movement_type": data.movement_type,
            "new_quantity": stock.quantity,
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error saving stock movement: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Gagal menyimpan pergerakan stok: {str(e)}")


@router.post("/opname")
def create_opname(
    data: OpnameIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    loc = data.location.lower().strip()
    if loc not in VALID_INV_LOCATIONS:
        raise HTTPException(status_code=400, detail=f"location harus salah satu dari: {', '.join(VALID_INV_LOCATIONS)}.")
    require_department_access(current_user, loc)

    try:
        part = _get_or_create_part(db, data.code.strip(), data.name)
        stock = _get_or_create_stock_row(db, part.id, loc)

        system_qty = stock.quantity
        difference = data.counted_quantity - system_qty

        db.add(PartStockOpname(
            part_id=part.id,
            location=loc,
            system_quantity=system_qty,
            counted_quantity=data.counted_quantity,
            difference=difference,
            note=data.note,
            performed_by_user_id=current_user.id,
        ))
        # Stok opname menyesuaikan jumlah sistem supaya sama dengan hasil hitung fisik.
        stock.quantity = data.counted_quantity

        db.commit()
        return {
            "status": "success",
            "code": part.code,
            "name": part.name,
            "location": loc,
            "system_quantity": system_qty,
            "counted_quantity": data.counted_quantity,
            "difference": difference,
        }
    except Exception as e:
        db.rollback()
        logger.error(f"Error saving stock opname: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Gagal menyimpan stok opname: {str(e)}")


# ---------------- Laporan Excel ----------------

def _excel_response(headers, rows, sheet_title, filename):
    excel_file = generate_inventory_excel(headers, rows, sheet_title)
    return StreamingResponse(
        excel_file,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/report/stock-list")
def report_stock_list(
    location: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    loc = location.lower().strip()
    require_department_access(current_user, loc)
    rows = (
        db.query(PartStock, PartCatalog)
        .join(PartCatalog, PartStock.part_id == PartCatalog.id)
        .filter(PartStock.location == loc)
        .order_by(PartCatalog.name)
        .all()
    )
    data = [[p.code, p.name or "-", s.quantity, p.unit_price or 0] for s, p in rows]
    filename = f"Stok_Sparepart_{loc}_{datetime.utcnow().strftime('%Y%m%d')}.xlsx"
    return _excel_response(["Kode Sparepart", "Nama Sparepart", "Jumlah Stok", "Harga Satuan"], data, f"Stok {loc}", filename)


@router.get("/report/movements")
def report_movements(
    location: str,
    movement_type: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    loc = location.lower().strip()
    require_department_access(current_user, loc)
    if movement_type not in MOVEMENT_RULES.get(loc, {}):
        raise HTTPException(status_code=400, detail="movement_type tidak valid untuk lokasi ini.")

    rows = (
        db.query(PartStockMovement, PartCatalog)
        .join(PartCatalog, PartStockMovement.part_id == PartCatalog.id)
        .filter(PartStockMovement.location == loc, PartStockMovement.movement_type == movement_type)
        .order_by(desc(PartStockMovement.created_at))
        .all()
    )
    data = [
        [m.created_at.strftime("%Y-%m-%d %H:%M") if m.created_at else "-", p.code, p.name or "-", m.quantity, m.note or "-"]
        for m, p in rows
    ]
    label = MOVEMENT_LABELS.get(movement_type, movement_type)
    filename = f"Laporan_{label.replace(' ', '_')}_{loc}_{datetime.utcnow().strftime('%Y%m%d')}.xlsx"
    return _excel_response(["Tanggal", "Kode Sparepart", "Nama Sparepart", "Jumlah", "Catatan"], data, label[:31], filename)


@router.get("/report/opname")
def report_opname(
    location: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    loc = location.lower().strip()
    require_department_access(current_user, loc)
    rows = (
        db.query(PartStockOpname, PartCatalog)
        .join(PartCatalog, PartStockOpname.part_id == PartCatalog.id)
        .filter(PartStockOpname.location == loc)
        .order_by(desc(PartStockOpname.created_at))
        .all()
    )
    data = [
        [
            o.created_at.strftime("%Y-%m-%d %H:%M") if o.created_at else "-",
            p.code, p.name or "-", o.system_quantity, o.counted_quantity, o.difference, o.note or "-",
        ]
        for o, p in rows
    ]
    filename = f"Stok_Opname_{loc}_{datetime.utcnow().strftime('%Y%m%d')}.xlsx"
    return _excel_response(
        ["Tanggal", "Kode Sparepart", "Nama Sparepart", "Stok Sistem", "Hasil Hitung Fisik", "Selisih", "Catatan"],
        data, f"Opname {loc}", filename,
    )
