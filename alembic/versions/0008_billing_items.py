"""Tambah tabel ticket_billing_items, document_counters, dan field billing baru di service_tickets.

PENTING SOAL KEAMANAN DATA:
- Semua kolom baru di service_tickets NULLABLE - tiket lama tetap valid.
- Tabel baru murni tambahan, tidak menyentuh tabel yang sudah ada.
- Idempotent: mengecek dulu sebelum menambah kolom/tabel.

Revision ID: 0008_billing_items
Revises: 0007_payment_fields
Create Date: 2026-09-09
"""
from alembic import op
import sqlalchemy as sa

revision = "0008_billing_items"
down_revision = "0007_payment_fields"
branch_labels = None
depends_on = None

NEW_TICKET_COLUMNS = [
    ("invoice_owner_name", sa.String(length=150)),
    ("customer_email", sa.String(length=200)),
    ("invoice_address", sa.Text()),
    ("ppn_free", sa.Boolean()),
    ("use_manual_price_breakdown", sa.Boolean()),
    ("pph23_amount", sa.Float()),
    ("admin_bank_fee", sa.Float()),
    ("invoice_number", sa.String(length=50)),
    ("quotation_number", sa.String(length=50)),
]


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    if "service_tickets" in existing_tables:
        existing_columns = {c["name"] for c in inspector.get_columns("service_tickets")}
        for col_name, col_type in NEW_TICKET_COLUMNS:
            if col_name not in existing_columns:
                nullable_kwargs = {"nullable": True}
                if col_name in ("ppn_free", "use_manual_price_breakdown"):
                    op.add_column("service_tickets", sa.Column(col_name, col_type, nullable=False, server_default=sa.false()))
                else:
                    op.add_column("service_tickets", sa.Column(col_name, col_type, **nullable_kwargs))

    if "ticket_billing_items" not in existing_tables:
        op.create_table(
            "ticket_billing_items",
            sa.Column("id", sa.Integer(), primary_key=True, index=True),
            sa.Column("ticket_id", sa.Integer(), sa.ForeignKey("service_tickets.id"), nullable=False),
            sa.Column("sequence", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("service_type", sa.String(length=20), nullable=True, server_default="Perbaikan"),
            sa.Column("product_category", sa.String(length=50), nullable=True),
            sa.Column("device_model", sa.String(length=100), nullable=True),
            sa.Column("serial_number", sa.String(length=50), nullable=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("quantity", sa.Integer(), nullable=True, server_default="1"),
            sa.Column("price", sa.Float(), nullable=True, server_default="0"),
            sa.Column("ref_ticket_number", sa.String(length=30), nullable=True),
        )

    if "document_counters" not in existing_tables:
        op.create_table(
            "document_counters",
            sa.Column("id", sa.Integer(), primary_key=True, index=True),
            sa.Column("doc_type", sa.String(length=10), nullable=False),
            sa.Column("year", sa.Integer(), nullable=False),
            sa.Column("last_number", sa.Integer(), nullable=False, server_default="0"),
            sa.UniqueConstraint("doc_type", "year", name="uq_doc_counter_type_year"),
        )


def downgrade():
    pass
