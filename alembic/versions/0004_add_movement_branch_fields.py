"""Tambah kolom device_model, part_status, related_branch di part_stock_movements.

PENTING SOAL KEAMANAN DATA:
- Semua kolom baru NULLABLE, baris data movement yang sudah ada tetap valid
  tanpa perlu diubah.
- Idempotent: mengecek dulu kolom yang sudah ada sebelum menambahkan.

Revision ID: 0004_add_movement_branch_fields
Revises: 0003_add_branch_pickup_catalog
Create Date: 2026-09-09
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_add_movement_branch_fields"
down_revision = "0003_add_branch_pickup_catalog"
branch_labels = None
depends_on = None

NEW_COLUMNS = [
    ("device_model", sa.String(length=100)),
    ("part_status", sa.String(length=50)),
    ("related_branch", sa.String(length=150)),
]


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if "part_stock_movements" in inspector.get_table_names():
        existing_columns = {c["name"] for c in inspector.get_columns("part_stock_movements")}
        for col_name, col_type in NEW_COLUMNS:
            if col_name not in existing_columns:
                op.add_column("part_stock_movements", sa.Column(col_name, col_type, nullable=True))


def downgrade():
    # Sengaja tidak diimplementasikan detail (downgrade berisiko menghapus data).
    pass
