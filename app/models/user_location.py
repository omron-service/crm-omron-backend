from sqlalchemy import Column, Integer, String, Enum
from sqlalchemy.orm import relationship
from app.db.session import Base
from app.models.enums import LocationType

# CATATAN PENTING: class `User` yang tadinya ada di file ini SUDAH DIHAPUS
# karena bentrok (nama tabel "users" sama persis, kolom berbeda) dengan
# `User` di app/models/schema.py - yaitu User yang SUNGGUHAN dipakai oleh
# seluruh sistem login/auth yang sudah berjalan. Relationship `users` di
# bawah ini ikut dihapus karena User versi ini sudah tidak ada.


class Location(Base):
    __tablename__ = "locations"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    code = Column(String(20), unique=True, index=True, nullable=False)
    location_type = Column(Enum(LocationType), nullable=False)
    address = Column(String(255), nullable=True)

    inventories = relationship("StockInventory", back_populates="location")