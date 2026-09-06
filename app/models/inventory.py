from sqlalchemy import Column, Integer, String, Numeric, ForeignKey, Enum, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.session import Base
from app.models.enums import MutationStatus

class SparePart(Base):
    __tablename__ = "spare_parts"
    id = Column(Integer, primary_key=True, index=True)
    part_number = Column(String(50), unique=True, index=True, nullable=False)
    name = Column(String(100), nullable=False)
    price = Column(Numeric(12, 2), default=0.0)

class StockInventory(Base):
    __tablename__ = "stock_inventories"
    id = Column(Integer, primary_key=True, index=True)
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=False)
    spare_part_id = Column(Integer, ForeignKey("spare_parts.id"), nullable=False)
    quantity = Column(Integer, default=0)

    location = relationship("Location", back_populates="inventories")
    spare_part = relationship("SparePart")

class StockMutation(Base):
    __tablename__ = "stock_mutations"
    id = Column(Integer, primary_key=True, index=True)
    sender_location_id = Column(Integer, ForeignKey("locations.id"), nullable=False)
    receiver_location_id = Column(Integer, ForeignKey("locations.id"), nullable=False)
    spare_part_id = Column(Integer, ForeignKey("spare_parts.id"), nullable=False)
    quantity = Column(Integer, nullable=False)
    status = Column(Enum(MutationStatus), default=MutationStatus.REQUESTED)
    created_at = Column(DateTime(timezone=True), server_default=func.now())