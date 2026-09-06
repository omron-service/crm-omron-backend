from pydantic import BaseModel, Field

class StockMutationCreate(BaseModel):
    sender_location_id: int
    receiver_location_id: int
    spare_part_id: int
    quantity: int = Field(..., gt=0)