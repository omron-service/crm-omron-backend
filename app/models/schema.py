from sqlalchemy import Column, Integer, String, DateTime, Text, Numeric
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()

class ServiceTicket(Base):
    __tablename__ = "service_tickets"

    id = Column(Integer, primary_key=True, index=True)
    ticket_number = Column(String(50), unique=True, index=True, nullable=False)
    service_type = Column(String(20), nullable=False) # 'pusat', 'cabang', 'pickup'
    customer_name = Column(String(100), nullable=False)
    customer_phone = Column(String(20), nullable=False)
    branch_or_point = Column(String(100), nullable=True)
    device_model = Column(String(50), nullable=False)
    serial_number = Column(String(50), nullable=True)
    complaint = Column(Text, nullable=True)
    status = Column(String(50), default="Diterima")
    created_at = Column(DateTime, default=datetime.utcnow)

class PaymentRecord(Base):
    __tablename__ = "payment_records"

    id = Column(Integer, primary_key=True, index=True)
    ticket_number = Column(String(50), nullable=False)
    service_type = Column(String(20), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    payment_method = Column(String(50), nullable=True)
    payment_code = Column(String(50), unique=True, nullable=False)
    branch_or_point = Column(String(100), nullable=True)
    status = Column(String(50), default="Lunas")
    created_at = Column(DateTime, default=datetime.utcnow)

class InventoryPart(Base):
    __tablename__ = "inventory_parts"

    id = Column(Integer, primary_key=True, index=True)
    part_code = Column(String(50), unique=True, nullable=False)
    part_name = Column(String(100), nullable=False)
    inventory_type = Column(String(20), nullable=False) # 'pusat', 'cabang'
    category = Column(String(50), nullable=True)
    branch = Column(String(50), nullable=True)
    qty = Column(Integer, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
