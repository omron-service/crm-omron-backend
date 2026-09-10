import os
import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base

logger = logging.getLogger("uvicorn.error")

# SATU-SATUNYA Base untuk SELURUH aplikasi. Semua file model (schema.py,
# user_location.py, service.py, inventory.py) WAJIB import Base dari sini,
# supaya semuanya berbagi satu metadata yang sama dan Alembic bisa melihat
# seluruh tabel sekaligus tanpa bentrok.
Base = declarative_base()

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


# ---- KHUSUS ENDPOINT PUBLIK (/pickup-intake, /track) - Opsi 2 pengamanan ----
# Kalau PUBLIC_DATABASE_URL diisi (connection string user database yang HAK
# AKSESNYA DIBATASI - lihat sql_setup_public_db_user.sql), endpoint publik
# akan pakai koneksi itu, BUKAN koneksi utama yang penuh akses. Jadi kalau
# suatu saat ada celah di kode endpoint publik, dampaknya terbatas (user DB
# itu TIDAK BISA baca tabel users/password, TIDAK BISA DELETE/DROP apa pun).
#
# Kalau PUBLIC_DATABASE_URL belum diisi, otomatis JATUH KEMBALI (fallback) ke
# koneksi utama seperti sebelumnya - tidak ada yang rusak kalau Anda belum
# sempat setup user database terbatas ini.
PUBLIC_DATABASE_URL = os.getenv("PUBLIC_DATABASE_URL", "").strip()
if PUBLIC_DATABASE_URL:
    if PUBLIC_DATABASE_URL.startswith("postgres://"):
        PUBLIC_DATABASE_URL = PUBLIC_DATABASE_URL.replace("postgres://", "postgresql://", 1)
    public_engine = create_engine(
        PUBLIC_DATABASE_URL, pool_pre_ping=True, pool_recycle=300, pool_size=5, max_overflow=10,
    )
    PublicSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=public_engine)
    logger.info("PUBLIC_DATABASE_URL terdeteksi - endpoint publik akan pakai user database terbatas.")
else:
    PublicSessionLocal = SessionLocal
    logger.warning(
        "PUBLIC_DATABASE_URL belum diatur - endpoint publik (/pickup-intake, /track) "
        "masih memakai koneksi database UTAMA (akses penuh). Lihat panduan Opsi 2 "
        "utk mengatur user database terbatas demi keamanan lebih baik."
    )


def get_public_db():
    db = PublicSessionLocal()
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
    import app.db.base  # noqa: F401  (memastikan SEMUA model sudah ter-load ke metadata sebelum create_all)

    try:
        Base.metadata.create_all(bind=engine)
    except Exception as e:
        logger.error(f"Gagal inisialisasi skema tabel: {str(e)}")
        raise
