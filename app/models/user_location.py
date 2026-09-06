from sqlalchemy import Column, Integer, String, Enum, ForeignKey
from sqlalchemy.orm import relationship
from app.db.session import Base
from app.models.enums import LocationType, UserRole

class Location(Base):
    __tablename__ = "locations"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    code = Column(String(20), unique=True, index=True, nullable=False)
    location_type = Column(Enum(LocationType), nullable=False)
    address = Column(String(255), nullable=True)

    users = relationship("User", back_populates="location")
    inventories = relationship("StockInventory", back_populates="location")

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(100), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(100), nullable=False)
    role = Column(Enum(UserRole), nullable=False, default=UserRole.TECHNICIAN)
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=True)

    location = relationship("Location", back_populates="users")