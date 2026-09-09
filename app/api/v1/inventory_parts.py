import logging
from datetime import datetime
from io import BytesIO
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
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

# Jenis pergerakan yang boleh DIBUAT MANUAL oleh staff (tombol + / upload Excel)
# di masing-masing lokasi, dan arahnya (+1 = item masuk, -1 = item keluar).
# CATATAN: "terpakai_pusat"/"terpakai_cabang" SENGAJA tidak ada di sini lagi
# (tombol manualnya dihapus) - tapi "terpakai_pusat" TETAP otomatis tercatat
# lewat sparepart tiket Pickup Center (lihat _deduct_pusat_stock_for_pickup di
# services_api.py, jalur kode terpisah yang tidak lewat validasi dict ini).
MOVEMENT_RULES = {
    "pusat": {
        "terima_gudang": 1,        # Terima sparepart dari Gudang (item masuk)
        "kirim_ke_cabang": -1,     # Kirim sparepart ke Cabang (item keluar)
        "terima_dari_cabang": 1,   # Terima sparepart dari Cabang (item masuk)
    },
    "cabang": {
        "terima_dari_pusat": 1,      # Terima sparepart dari Pusat (item masuk)
        "kirim_balik_ke_pusat": -1,  # Kirim balik sparepart ke Pusat (item keluar)
    },
}

# Jenis pergerakan yang BOLEH DILAPORKAN (buat download Excel) per lokasi - beda
# dari MOVEMENT_RULES di atas karena "terpakai_pusat" tetap harus bisa dilaporkan
# meski tidak lagi bisa dibuat manual (datanya otomatis dari tiket Pickup Center).
REPORTABLE_MOVEMENT_TYPES = {
    "pusat": {**MOVEMENT_RULES["pusat"], "terpakai_pusat": -1},
    "cabang": dict(MOVEMENT_RULES["cabang"]),
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


def _apply_single_movement(db: Session, loc: str, movement_type: str, code: str, name: Optional[str], quantity: int, note: Optional[str], user_id: int):
    """
    Logika inti SATU baris pergerakan stok - dipakai bersama oleh endpoint
    manual (/movement) MAUPUN upload massal Excel (/movement/bulk-upload),
    supaya keduanya konsisten (validasi lokasi, jenis pergerakan, stok tidak
    boleh minus, sama persis).
    """
    allowed = MOVEMENT_RULES.get(loc, {})
    if movement_type not in allowed:
        raise ValueError(
            f"movement_type '{movement_type}' tidak berlaku untuk lokasi '{loc}'. "
            f"Pilihan yang valid: {', '.join(allowed.keys())}."
        )
    if not code or not code.strip():
        raise ValueError("Kode Sparepart wajib diisi.")
    if not quantity or quantity <= 0:
        raise ValueError("Jumlah harus lebih dari 0.")

    direction = allowed[movement_type]
    part = _get_or_create_part(db, code.strip(), name)
    stock = _get_or_create_stock_row(db, part.id, loc)

    new_quantity = stock.quantity + (direction * quantity)
    if new_quantity < 0:
        raise ValueError(f"Stok tidak mencukupi untuk '{part.code}'. Stok saat ini {stock.quantity}, tidak bisa mengurangi {quantity}.")

    stock.quantity = new_quantity
    db.add(PartStockMovement(
        part_id=part.id, location=loc, movement_type=movement_type,
        quantity=quantity, note=note, performed_by_user_id=user_id,
    ))
    return part, stock


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

    try:
        part, stock = _apply_single_movement(
            db, loc, data.movement_type, data.code, data.name, data.quantity, data.note, current_user.id
        )
        db.commit()
        return {
            "status": "success",
            "code": part.code,
            "name": part.name,
            "location": loc,
            "movement_type": data.movement_type,
            "new_quantity": stock.quantity,
        }
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        db.rollback()
        logger.error(f"Error saving stock movement: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Gagal menyimpan pergerakan stok: {str(e)}")


@router.get("/movement/template")
def download_movement_template(
    current_user: User = Depends(get_current_user),
):
    """
    Contoh format Excel untuk upload massal pergerakan stok (Terima dari
    Gudang / Kirim ke Cabang / Terima dari Cabang / Terima dari Pusat / Kirim
    Balik ke Pusat - kolomnya sama persis untuk semua jenis, cuma jenis
    pergerakannya dipilih terpisah saat upload, bukan dari isi file).
    """
    headers = ["Kode Sparepart", "Nama Sparepart", "Jumlah", "Catatan"]
    example_rows = [
        ["LCD-01", "LCD Panel HEM-7120", 10, "Contoh baris - boleh dihapus"],
        ["SNS-02", "Sensor Suhu", 5, ""],
    ]
    excel_file = generate_inventory_excel(headers, example_rows, "Contoh Format")
    return StreamingResponse(
        excel_file,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=Contoh_Format_Upload_Stok.xlsx"},
    )


@router.post("/movement/bulk-upload")
def bulk_upload_movements(
    location: str = Form(...),
    movement_type: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Upload massal pergerakan stok dari Excel, kolom: Kode Sparepart, Nama
    Sparepart, Jumlah, Catatan (baris header terdeteksi otomatis & dilewati).
    Setiap baris diproses dengan aturan yang SAMA PERSIS dengan input manual
    satu-satu (stok tidak boleh minus, dst) - baris yang gagal dilaporkan
    jelas tanpa membatalkan baris lain yang valid.
    """
    loc = location.lower().strip()
    if loc not in VALID_INV_LOCATIONS:
        raise HTTPException(status_code=400, detail=f"location harus salah satu dari: {', '.join(VALID_INV_LOCATIONS)}.")
    require_department_access(current_user, loc)

    allowed = MOVEMENT_RULES.get(loc, {})
    if movement_type not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"movement_type '{movement_type}' tidak berlaku untuk lokasi '{loc}'. "
                   f"Pilihan yang valid: {', '.join(allowed.keys())}.",
        )

    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="File harus berformat .xlsx (Excel).")

    try:
        import openpyxl
        wb = openpyxl.load_workbook(BytesIO(file.file.read()), data_only=True)
        ws = wb.active
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Gagal membaca file Excel: {str(e)}")

    rows = list(ws.iter_rows(min_row=1, values_only=True))
    if not rows:
        raise HTTPException(status_code=400, detail="File Excel kosong.")

    header_probe = " ".join(str(v).lower() for v in rows[0] if v)
    start_row = 1 if ("kode" in header_probe or "sparepart" in header_probe or "jumlah" in header_probe) else 0

    berhasil, errors = 0, []
    for idx, row in enumerate(rows[start_row:], start=start_row + 1):
        if not row or not any(row):
            continue
        code = str(row[0]).strip() if len(row) > 0 and row[0] is not None else ""
        name = str(row[1]).strip() if len(row) > 1 and row[1] is not None else None
        try:
            quantity = int(row[2]) if len(row) > 2 and row[2] is not None else 0
        except (ValueError, TypeError):
            quantity = 0
        note = str(row[3]).strip() if len(row) > 3 and row[3] is not None else None

        try:
            _apply_single_movement(db, loc, movement_type, code, name, quantity, note, current_user.id)
            berhasil += 1
        except ValueError as e:
            errors.append({"row": idx, "reason": str(e)})
        except Exception as e:
            errors.append({"row": idx, "reason": f"Error tidak terduga: {str(e)}"})

    db.commit()
    return {
        "status": "success",
        "total_baris_diproses": len(rows) - start_row,
        "berhasil": berhasil,
        "gagal": len(errors),
        "detail_gagal": errors[:50],
    }


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
    if movement_type not in REPORTABLE_MOVEMENT_TYPES.get(loc, {}):
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
