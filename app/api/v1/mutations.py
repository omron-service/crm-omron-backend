from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.inventory import StockInventory, StockMutation
from app.models.enums import MutationStatus
from app.schemas.inventory import StockMutationCreate

router = APIRouter(prefix="/api/v1/inventory/mutations", tags=["Inventory Mutations"])

@router.post("/request", status_code=status.HTTP_201_CREATED)
def request_mutation(payload: StockMutationCreate, db: Session = Depends(get_db)):
    mutation = StockMutation(**payload.model_dump(), status=MutationStatus.REQUESTED)
    db.add(mutation)
    db.commit()
    db.refresh(mutation)
    return mutation

@router.post("/{mutation_id}/approve")
def approve_mutation(mutation_id: int, db: Session = Depends(get_db)):
    try:
        with db.begin():
            mutation = db.query(StockMutation).filter(
                StockMutation.id == mutation_id, 
                StockMutation.status == MutationStatus.REQUESTED
            ).with_for_update().first()
            
            if not mutation:
                raise HTTPException(status_code=400, detail="Mutasi tidak valid atau sudah diproses.")
            
            sender_stk = db.query(StockInventory).filter(
                StockInventory.location_id == mutation.sender_location_id, 
                StockInventory.spare_part_id == mutation.spare_part_id
            ).with_for_update().first()
            
            if not sender_stk or sender_stk.quantity < mutation.quantity:
                raise HTTPException(status_code=400, detail="Stok pengirim tidak mencukupi.")

            sender_stk.quantity -= mutation.quantity
            mutation.status = MutationStatus.IN_TRANSIT
            db.flush()
            
        return {"message": "Mutasi disetujui & stok berhasil dipotong"}
    except Exception as e:
        db.rollback()
        raise e