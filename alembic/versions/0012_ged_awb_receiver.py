"""Tambah kolom awb_number & received_by_name (integrasi GED - Nama Penerima).

Revision ID: 0012_ged_awb_receiver
Revises: 0011_ged_shipping
Create Date: 2026-09-11
"""
from alembic import op
import sqlalchemy as sa

revision = "0012_ged_awb_receiver"
down_revision = "0011_ged_shipping"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "service_tickets" in inspector.get_table_names():
        existing_columns = {c["name"] for c in inspector.get_columns("service_tickets")}
        # SENGAJA TIDAK diberi UniqueConstraint pada awb_number - beberapa
        # tiket dari Pickup Center yang sama bisa sah-sah saja berbagi 1 AWB
        # yang sama (dikirim jadi satu paket sekaligus oleh kurir).
        if "awb_number" not in existing_columns:
            op.add_column("service_tickets", sa.Column("awb_number", sa.String(length=50), nullable=True))
        if "received_by_name" not in existing_columns:
            op.add_column("service_tickets", sa.Column("received_by_name", sa.String(length=150), nullable=True))


def downgrade():
    pass
