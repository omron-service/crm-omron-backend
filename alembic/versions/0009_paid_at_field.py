"""Tambah kolom paid_at (Tanggal Bayar - diisi otomatis dari notifikasi DOKU).

Revision ID: 0009_paid_at_field
Revises: 0008_billing_items
Create Date: 2026-09-10
"""
from alembic import op
import sqlalchemy as sa

revision = "0009_paid_at_field"
down_revision = "0008_billing_items"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "service_tickets" in inspector.get_table_names():
        existing_columns = {c["name"] for c in inspector.get_columns("service_tickets")}
        if "paid_at" not in existing_columns:
            op.add_column("service_tickets", sa.Column("paid_at", sa.DateTime(), nullable=True))
        if "invoice_created_at" not in existing_columns:
            op.add_column("service_tickets", sa.Column("invoice_created_at", sa.DateTime(), nullable=True))


def downgrade():
    pass
