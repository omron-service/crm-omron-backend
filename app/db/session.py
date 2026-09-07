import os
import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger("uvicorn.error")

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./local_crm.db")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

if "sqlite" in DATABASE_URL:
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_recycle=300,
        pool_size=10,
        max_overflow=20,
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """
    PENTING SOAL KEAMANAN DATA:
    Base.metadata.create_all() HANYA membuat tabel yang BELUM ADA di database
    (setara "CREATE TABLE IF NOT EXISTS"). Fungsi ini TIDAK PERNAH menghapus
    tabel, TIDAK PERNAH menghapus baris data, dan TIDAK PERNAH mengubah kolom
    yang sudah ada. Aman dipanggil berkali-kali setiap kali aplikasi start.

    ATURAN WAJIB ke depannya:
    - Kalau butuh MENAMBAH kolom baru      -> pakai Alembic migration (ADD COLUMN).
    - Kalau butuh MENGUBAH tipe/nama kolom  -> pakai Alembic migration (ALTER COLUMN).
    - JANGAN PERNAH memanggil Base.metadata.drop_all() di kode aplikasi.
    - JANGAN PERNAH membuat ulang (recreate) tabel service_tickets untuk "membersihkan"
      struktur. Semua perubahan struktur = migration, bukan drop+create.
    """
    from app.models.schema import Base  # import di sini supaya semua model sudah ter-load ke metadata

    try:
        Base.metadata.create_all(bind=engine)
    except Exception as e:
        logger.error(f"Gagal inisialisasi skema tabel: {str(e)}")
        raise
