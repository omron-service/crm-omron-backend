from sqlalchemy import Column, Integer, String, Enum, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.session import Base
from app.models.enums import TicketStatus, PaymentStatusEnum

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
    tickets = relationship("ServiceTicket", back_populates="device_model")

class ServiceTicket(Base):
    __tablename__ = "service_tickets"
    id = Column(Integer, primary_key=True, index=True)
    ticket_number = Column(String(50), unique=True, index=True, nullable=False)
    customer_name = Column(String(100), nullable=False)
    customer_phone = Column(String(20), nullable=False)
    device_model_id = Column(Integer, ForeignKey("device_models.id"), nullable=False)
    serial_number = Column(String(100), nullable=False)
    problem_description = Column(Text, nullable=False)
    status = Column(Enum(TicketStatus), default=TicketStatus.RECEIVED)
    payment_status = Column(Enum(PaymentStatusEnum), default=PaymentStatusEnum.UNPAID)
    current_location_id = Column(Integer, ForeignKey("locations.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    device_model = relationship("DeviceModel", back_populates="tickets")
    current_location = relationship("Location")