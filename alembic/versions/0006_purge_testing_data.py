"""Bersihkan riwayat testing Inventory Part (permanen, sekali jalan).

PENTING - INI MIGRATION DATA (bukan skema), DIJALANKAN OTOMATIS SEKALI SAJA:
- Menghapus SEMUA baris di part_stock_movements (riwayat pergerakan stok) dan
  part_stock_opname (riwayat stok opname).
- Mengembalikan SEMUA angka di part_stock.quantity menjadi 0.

YANG TIDAK DISENTUH (sengaja dipertahankan):
- part_catalog (kode, nama, Status, Model Alat sparepart) TETAP ADA - ini data
  referensi asli produk Omron, bukan data testing.
- Semua tabel lain (tiket servis, user, cabang, pickup center, dst) TIDAK
  disentuh sama sekali.

Sesuai instruksi eksplisit user untuk membersihkan riwayat hasil testing tombol
"Reset Stok (Testing)" yang sudah dihapus dari aplikasi.

Revision ID: 0006_purge_testing_data
Revises: 0005_part_catalog_status
Create Date: 2026-09-09
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_purge_testing_data"
down_revision = "0005_part_catalog_status"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    if "part_stock_movements" in existing_tables:
        conn.execute(sa.text("DELETE FROM part_stock_movements"))

    if "part_stock_opname" in existing_tables:
        conn.execute(sa.text("DELETE FROM part_stock_opname"))

    if "part_stock" in existing_tables:
        conn.execute(sa.text("UPDATE part_stock SET quantity = 0"))


def downgrade():
    # Data yang sudah dihapus tidak bisa dikembalikan - downgrade sengaja
    # tidak diimplementasikan.
    pass
