from sqlalchemy import Column, Integer, String, Text, Float, DateTime
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()

class ServiceTicket(Base):
    __tablename__ = "service_tickets"

    id = Column(Integer, primary_key=True, index=True)
    ticket_number = Column(String(50), unique=True, index=True, nullable=False)
    service_type = Column(String(50), default="pusat", nullable=True)
    customer_name = Column(String(100), nullable=False)
    customer_phone = Column(String(50), nullable=False)
    branch_or_point = Column(String(100), default="-", nullable=True)
    device_model = Column(String(100), default="HEM-7120", nullable=True)
    serial_number = Column(String(100), default="-", nullable=True)
    warranty_status = Column(String(50), default="Out of Warranty", nullable=True)
    complaint = Column(Text, default="-", nullable=True)
    status = Column(String(50), default="Diproses", nullable=True)
    total_price = Column(Float, default=0.0, nullable=True)
    payment_status = Column(String(50), default="Belum Lunas", nullable=True)
    payment_code = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class PaymentRecord(Base):
    __tablename__ = "payment_records"

    id = Column(Integer, primary_key=True, index=True)
    ticket_number = Column(String(50), index=True, nullable=False)
    amount = Column(Float, nullable=False)
    payment_code = Column(String(50), nullable=True)
    status = Column(String(50), default="Pending")
    created_at = Column(DateTime, default=datetime.utcnow)

class InventoryPart(Base):
    __tablename__ = "inventory_parts"

    id = Column(Integer, primary_key=True, index=True)
    part_code = Column(String(50), unique=True, index=True, nullable=False)
    part_name = Column(String(100), nullable=False)
    category = Column(String(50), nullable=True)
    location = Column(String(50), default="pusat")
    qty = Column(Integer, default=0)
