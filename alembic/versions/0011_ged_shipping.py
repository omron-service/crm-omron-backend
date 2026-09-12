"""Tambah kolom shipping_status/shipping_updated_at + tabel shipment_tracking_events (integrasi GED).

Revision ID: 0011_ged_shipping
Revises: 0010_login_otp
Create Date: 2026-09-11
"""
from alembic import op
import sqlalchemy as sa

revision = "0011_ged_shipping"
down_revision = "0010_login_otp"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if "service_tickets" in inspector.get_table_names():
        existing_columns = {c["name"] for c in inspector.get_columns("service_tickets")}
        if "shipping_status" not in existing_columns:
            op.add_column("service_tickets", sa.Column("shipping_status", sa.String(length=50), nullable=True))
        if "shipping_updated_at" not in existing_columns:
            op.add_column("service_tickets", sa.Column("shipping_updated_at", sa.DateTime(), nullable=True))

    if "shipment_tracking_events" not in inspector.get_table_names():
        op.create_table(
            "shipment_tracking_events",
            sa.Column("id", sa.Integer(), primary_key=True, index=True),
            sa.Column("ticket_id", sa.Integer(), sa.ForeignKey("service_tickets.id"), nullable=False),
            sa.Column("status", sa.String(length=50), nullable=False),
            sa.Column("raw_payload", sa.Text(), nullable=True),
            sa.Column("event_timestamp", sa.DateTime(), nullable=True),
            sa.Column("received_at", sa.DateTime(), nullable=True),
        )


def downgrade():
    pass
