from sqlalchemy import Column, Integer, String, Text, DateTime, Float
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()

class ServiceTicket(Base):
    __tablename__ = "service_tickets"

    id = Column(Integer, primary_key=True, index=True)
    ticket_number = Column(String(50), unique=True, index=True, nullable=False)
    
    # Kategori Lokasi Input
    service_type = Column(String(20), index=True, default="pusat") # pusat, cabang, pickup
    created_by_location = Column(String(50), index=True, default="PUSAT_JAKARTA") # PUSAT_JAKARTA, CABANG_BANDUNG, PKP_SURABAYA, dll
    
    # Data Pelanggan
    customer_name = Column(String(100), nullable=False)
    customer_phone = Column(String(30), nullable=False)
    customer_phone_2 = Column(String(30), nullable=True)
    customer_address = Column(Text, nullable=True)
    province = Column(String(50), nullable=True)
    city = Column(String(50), nullable=True)
    branch_or_point = Column(String(100), nullable=True)

    # Data Produk
    product_category = Column(String(50), nullable=True)
    device_model = Column(String(50), nullable=False)
    serial_number = Column(String(50), nullable=True)
    accessories = Column(String(100), nullable=True)
    warranty_status = Column(String(30), default="Out of Warranty")
    warranty_period = Column(String(20), nullable=True)
    product_origin = Column(String(50), nullable=True)

    # Data Servis
    complaint = Column(Text, nullable=True)
    technician_analysis = Column(Text, nullable=True)
    symptom_code = Column(String(30), nullable=True)
    leadtime_days = Column(Integer, default=1)
    notes = Column(Text, nullable=True)
    remarks = Column(String(100), nullable=True)
    status = Column(String(50), default="Diproses")

    # Payment
    total_price = Column(Float, default=0.0)
    payment_code = Column(String(50), nullable=True)
    payment_status = Column(String(30), default="Belum Lunas")

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
