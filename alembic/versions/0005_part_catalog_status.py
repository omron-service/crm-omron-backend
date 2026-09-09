"""Tambah kolom status dan model_alat di part_catalog.

PENTING SOAL KEAMANAN DATA:
- Kolom baru NULLABLE - data sparepart yang sudah ada tetap valid tanpa perlu diubah.
- Idempotent: mengecek dulu apakah kolom sudah ada sebelum menambahkannya.

Revision ID: 0005_part_catalog_status
Revises: 0004_add_movement_branch_fields
Create Date: 2026-09-09
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_part_catalog_status"
down_revision = "0004_add_movement_branch_fields"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if "part_catalog" in inspector.get_table_names():
        cols = {c["name"] for c in inspector.get_columns("part_catalog")}
        if "status" not in cols:
            op.add_column("part_catalog", sa.Column("status", sa.String(length=20), nullable=True))
        if "model_alat" not in cols:
            op.add_column("part_catalog", sa.Column("model_alat", sa.String(length=150), nullable=True))


def downgrade():
    pass
