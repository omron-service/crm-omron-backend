"""Pecah stok Cabang per Nama Cabang - tambah branch_name di part_stock & service_tickets.

Revision ID: 0013_branch_stock_split
Revises: 0012_ged_awb_receiver
Create Date: 2026-09-12
"""
from alembic import op
import sqlalchemy as sa

revision = "0013_branch_stock_split"
down_revision = "0012_ged_awb_receiver"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    # 1. service_tickets.branch_name (nama cabang SPESIFIK utk tiket Cabang)
    if "service_tickets" in inspector.get_table_names():
        existing_columns = {c["name"] for c in inspector.get_columns("service_tickets")}
        if "branch_name" not in existing_columns:
            op.add_column("service_tickets", sa.Column("branch_name", sa.String(length=150), nullable=True))

    # 2. part_stock.branch_name + ganti UniqueConstraint
    if "part_stock" in inspector.get_table_names():
        existing_columns = {c["name"] for c in inspector.get_columns("part_stock")}
        if "branch_name" not in existing_columns:
            # SQLite tidak bisa ALTER TABLE ADD COLUMN NOT NULL tanpa default
            # langsung kalau tabel sudah ada isinya - makanya isi default "" dulu.
            op.add_column("part_stock", sa.Column("branch_name", sa.String(length=150), nullable=False, server_default=""))

            # Baris "cabang" yang SUDAH ADA (dari sebelum fitur ini) tidak bisa
            # diketahui itu cabang yang mana - beri tanda JELAS supaya staff
            # tahu harus rekonsiliasi manual lewat Stok Opname per cabang asli.
            conn.execute(sa.text(
                "UPDATE part_stock SET branch_name = '(Belum Dipisah - Perlu Stok Opname)' WHERE location = 'cabang'"
            ))

        # Ganti UniqueConstraint lama (part_id, location) jadi (part_id, location, branch_name).
        existing_constraints = {c["name"] for c in inspector.get_unique_constraints("part_stock")}
        with op.batch_alter_table("part_stock") as batch_op:
            if "uq_part_stock_part_location" in existing_constraints:
                batch_op.drop_constraint("uq_part_stock_part_location", type_="unique")
            if "uq_part_stock_part_location_branch" not in existing_constraints:
                batch_op.create_unique_constraint(
                    "uq_part_stock_part_location_branch", ["part_id", "location", "branch_name"]
                )


    # 3. part_stock_opname.branch_name (nama cabang spesifik yg dihitung fisik)
    if "part_stock_opname" in inspector.get_table_names():
        existing_columns = {c["name"] for c in inspector.get_columns("part_stock_opname")}
        if "branch_name" not in existing_columns:
            op.add_column("part_stock_opname", sa.Column("branch_name", sa.String(length=150), nullable=True))


def downgrade():
    pass
