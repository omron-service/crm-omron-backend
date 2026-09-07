"""Tambah tabel Inventory Part: part_catalog, part_stock, part_stock_movements, part_stock_opname.

PENTING SOAL KEAMANAN DATA:
- Migration ini HANYA membuat tabel BARU yang belum ada sebelumnya. Tidak ada
  ALTER/DROP terhadap tabel yang sudah berjalan (service_tickets, users, dll).
- Idempotent: mengecek dulu apakah tabel sudah ada sebelum membuatnya, jadi
  aman dijalankan berkali-kali (mis. kalau init_db() sudah lebih dulu membuat
  tabel ini secara otomatis saat container start).

Revision ID: 0002_add_inventory_part
Revises: 0001_add_ticket_fields
Create Date: 2026-09-07
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0002_add_inventory_part"
down_revision = "0001_add_ticket_fields"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    if "part_catalog" not in existing_tables:
        op.create_table(
            "part_catalog",
            sa.Column("id", sa.Integer(), primary_key=True, index=True),
            sa.Column("code", sa.String(length=50), nullable=False, unique=True, index=True),
            sa.Column("name", sa.String(length=150), nullable=True),
            sa.Column("unit_price", sa.Float(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )

    if "part_stock" not in existing_tables:
        op.create_table(
            "part_stock",
            sa.Column("id", sa.Integer(), primary_key=True, index=True),
            sa.Column("part_id", sa.Integer(), sa.ForeignKey("part_catalog.id"), nullable=False),
            sa.Column("location", sa.String(length=20), nullable=False, index=True),
            sa.Column("quantity", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("part_id", "location", name="uq_part_stock_part_location"),
        )

    if "part_stock_movements" not in existing_tables:
        op.create_table(
            "part_stock_movements",
            sa.Column("id", sa.Integer(), primary_key=True, index=True),
            sa.Column("part_id", sa.Integer(), sa.ForeignKey("part_catalog.id"), nullable=False),
            sa.Column("location", sa.String(length=20), nullable=False, index=True),
            sa.Column("movement_type", sa.String(length=30), nullable=False, index=True),
            sa.Column("quantity", sa.Integer(), nullable=False),
            sa.Column("note", sa.String(length=255), nullable=True),
            sa.Column("performed_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )

    if "part_stock_opname" not in existing_tables:
        op.create_table(
            "part_stock_opname",
            sa.Column("id", sa.Integer(), primary_key=True, index=True),
            sa.Column("part_id", sa.Integer(), sa.ForeignKey("part_catalog.id"), nullable=False),
            sa.Column("location", sa.String(length=20), nullable=False, index=True),
            sa.Column("system_quantity", sa.Integer(), nullable=False),
            sa.Column("counted_quantity", sa.Integer(), nullable=False),
            sa.Column("difference", sa.Integer(), nullable=False),
            sa.Column("note", sa.String(length=255), nullable=True),
            sa.Column("performed_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )


def downgrade():
    # Sengaja tidak diimplementasikan detail (downgrade berisiko menghapus data
    # stok/riwayat yang sudah terisi). Kalau perlu rollback, lakukan manual
    # dengan hati-hati dan backup dulu.
    pass
