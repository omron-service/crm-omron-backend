"""Tambah kolom customer_id_number, payment_method, payment_url, payment_expired_at.

PENTING SOAL KEAMANAN DATA:
- Semua kolom baru NULLABLE - tiket lama tetap valid tanpa perlu diubah.
- Idempotent: mengecek dulu apakah kolom sudah ada sebelum menambahkannya.

Revision ID: 0007_payment_fields
Revises: 0006_purge_testing_data
Create Date: 2026-09-09
"""
from alembic import op
import sqlalchemy as sa

revision = "0007_payment_fields"
down_revision = "0006_purge_testing_data"
branch_labels = None
depends_on = None

NEW_COLUMNS = [
    ("customer_id_number", sa.String(length=30)),
    ("payment_method", sa.String(length=50)),
    ("payment_url", sa.String(length=500)),
    ("payment_expired_at", sa.DateTime()),
]


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if "service_tickets" in inspector.get_table_names():
        existing_columns = {c["name"] for c in inspector.get_columns("service_tickets")}
        for col_name, col_type in NEW_COLUMNS:
            if col_name not in existing_columns:
                op.add_column("service_tickets", sa.Column(col_name, col_type, nullable=True))


def downgrade():
    pass
