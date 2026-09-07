from sqlalchemy import Column, Integer, String, ForeignKey, Text
from sqlalchemy.orm import relationship
from app.db.session import Base

# CATATAN PENTING: class `ServiceTicket` yang tadinya ada di file ini SUDAH
# DIHAPUS karena bentrok (nama tabel "service_tickets" sama persis, kolom
# berbeda) dengan `ServiceTicket` di app/models/schema.py - yaitu ServiceTicket
# yang SUNGGUHAN dipakai oleh seluruh alur create-tiket pusat/cabang/pickup
# yang sudah berjalan. Relationship `tickets` di DeviceModel ikut dihapus
# karena ServiceTicket versi ini sudah tidak ada.


class DeviceCategory(Base):
    __tablename__ = "device_categories"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    models = relationship("DeviceModel", back_populates="category")


class DeviceModel(Base):
    __tablename__ = "device_models"
    id = Column(Integer, primary_key=True, index=True)
    category_id = Column(Integer, ForeignKey("device_categories.id"), nullable=False)
    model_name = Column(String(100), nullable=False)
    category = relationship("DeviceCategory", back_populates="models")