"""Tambah tabel master data: branch_catalog (Kelola Cabang) dan pickup_center_catalog (Kelola Pickup Center).

PENTING SOAL KEAMANAN DATA:
- Migration ini HANYA membuat tabel BARU. Tidak ada ALTER/DROP terhadap tabel
  yang sudah berjalan.
- Idempotent: mengecek dulu apakah tabel sudah ada sebelum membuatnya.

Revision ID: 0003_add_branch_pickup_catalog
Revises: 0002_add_inventory_part
Create Date: 2026-09-07
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_add_branch_pickup_catalog"
down_revision = "0002_add_inventory_part"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    if "branch_catalog" not in existing_tables:
        op.create_table(
            "branch_catalog",
            sa.Column("id", sa.Integer(), primary_key=True, index=True),
            sa.Column("name", sa.String(length=150), nullable=False),
            sa.Column("code", sa.String(length=20), nullable=False, unique=True, index=True),
            sa.Column("handled_by", sa.String(length=150), nullable=True),
            sa.Column("city", sa.String(length=100), nullable=True),
            sa.Column("address", sa.Text(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )

    if "pickup_center_catalog" not in existing_tables:
        op.create_table(
            "pickup_center_catalog",
            sa.Column("id", sa.Integer(), primary_key=True, index=True),
            sa.Column("store_long_code", sa.String(length=50), nullable=False, unique=True, index=True),
            sa.Column("store_name", sa.String(length=200), nullable=False),
            sa.Column("store_address", sa.Text(), nullable=True),
            sa.Column("city", sa.String(length=100), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )


def downgrade():
    # Sengaja tidak diimplementasikan detail (downgrade berisiko menghapus data
    # master cabang/pickup center yang sudah terisi).
    pass
