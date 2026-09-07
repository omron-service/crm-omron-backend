from sqlalchemy import Column, Integer, String, Text, DateTime, Float, Boolean, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime

# PENTING: Base TIDAK dibuat di sini lagi. Base yang sebenarnya sekarang hidup
# di app/db/session.py, dipakai bersama oleh SEMUA file model di project ini
# (schema.py, user_location.py, service.py, inventory.py) supaya tidak ada
# dua metadata terpisah yang bentrok satu sama lain.
from app.db.session import Base


class ServiceTicket(Base):
    """
    TIDAK ADA KOLOM LAMA YANG DIHAPUS ATAU DIUBAH DI SINI.
    Satu-satunya tambahan adalah `created_by_user_id` (nullable), jadi baris
    data lama yang sudah ada di database tetap valid tanpa perlu diubah.
    """
    __tablename__ = "service_tickets"
    id = Column(Integer, primary_key=True, index=True)
    ticket_number = Column(String(50), unique=True, index=True, nullable=False)

    # Kategori Lokasi Input - SATU tiket HANYA punya SATU service_type, ditentukan
    # sekali saat create dan tidak pernah ditulis ulang ke lokasi lain.
    service_type = Column(String(20), index=True, default="pusat")  # pusat, cabang, pickup
    created_by_location = Column(String(50), index=True, default="PUSAT_JAKARTA")

    # BARU: jejak siapa (user mana) yang membuat tiket ini. Nullable agar
    # baris lama (dibuat sebelum ada sistem login) tetap valid.
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_by = relationship("User", backref="tickets")

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


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(150), unique=True, index=True, nullable=False)
    full_name = Column(String(150), nullable=False)
    password_hash = Column(String(255), nullable=False)

    # "superadmin" = akses penuh semua lokasi + bisa kelola user lain
    # "staff"      = akses terbatas HANYA ke lokasi sesuai `department`
    role = Column(String(20), nullable=False, default="staff")

    # Departemen/lokasi kerja: "pusat", "cabang", atau "pickup".
    # NULL untuk superadmin (superadmin tidak dibatasi lokasi manapun).
    department = Column(String(20), nullable=True)

    is_active = Column(Boolean, default=True, nullable=False)  # nonaktifkan akun = soft, bukan delete
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class LocationCounter(Base):
    """
    Counter nomor urut tiket PER LOKASI, disimpan di tabel terpisah dan di-lock
    saat increment (SELECT ... FOR UPDATE). Ini mencegah race condition yang bisa
    menghasilkan dua tiket dengan nomor sama saat dua orang input bersamaan
    di lokasi yang sama.
    """
    __tablename__ = "location_counters"
    __table_args__ = (UniqueConstraint("service_type", name="uq_location_counters_service_type"),)

    id = Column(Integer, primary_key=True, index=True)
    service_type = Column(String(20), nullable=False, index=True)
    last_number = Column(Integer, nullable=False, default=0)
