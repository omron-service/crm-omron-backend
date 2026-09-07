"""Tambah field lengkap form tiket (instansi, tanggal, notifikasi) + tabel katalog model alat & sparepart per tiket.

PENTING SOAL KEAMANAN DATA:
- Semua kolom baru di service_tickets ditambahkan sebagai NULLABLE, jadi baris
  data tiket yang sudah ada di database TIDAK TERSENTUH dan tetap valid.
- Migration ini idempotent: mengecek dulu apakah kolom/tabel sudah ada sebelum
  membuatnya, jadi aman dijalankan berkali-kali tanpa error "already exists".
- TIDAK ADA satupun DROP COLUMN atau DROP TABLE di migration ini.

Revision ID: 0001_add_ticket_fields
Revises: 
Create Date: 2026-09-07
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0001_add_ticket_fields"
down_revision = None
branch_labels = None
depends_on = None


NEW_SERVICE_TICKET_COLUMNS = [
    ("instansi_name", sa.String(length=150)),
    ("received_date", sa.DateTime()),
    ("completed_date", sa.DateTime()),
    ("notif_receipt_whatsapp", sa.Boolean()),
    ("notif_receipt_email", sa.Boolean()),
    ("notif_report_whatsapp", sa.Boolean()),
    ("notif_report_email", sa.Boolean()),
]

BOOLEAN_NOTIF_COLUMNS = [
    "notif_receipt_whatsapp",
    "notif_receipt_email",
    "notif_report_whatsapp",
    "notif_report_email",
]


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    # ---------------- 1. Tambah kolom baru ke service_tickets ----------------
    if "service_tickets" in existing_tables:
        existing_columns = {c["name"] for c in inspector.get_columns("service_tickets")}

        for col_name, col_type in NEW_SERVICE_TICKET_COLUMNS:
            if col_name not in existing_columns:
                op.add_column("service_tickets", sa.Column(col_name, col_type, nullable=True))

        # Isi default False untuk baris LAMA di kolom notifikasi yang baru dibuat,
        # supaya tidak NULL (lebih rapi untuk ditampilkan di frontend sebagai checkbox).
        # Baris data lain sama sekali tidak diubah.
        for col_name in BOOLEAN_NOTIF_COLUMNS:
            if col_name not in existing_columns:
                op.execute(f"UPDATE service_tickets SET {col_name} = false WHERE {col_name} IS NULL")

    # ---------------- 2. Buat tabel device_model_catalog kalau belum ada ----------------
    if "device_model_catalog" not in existing_tables:
        op.create_table(
            "device_model_catalog",
            sa.Column("id", sa.Integer(), primary_key=True, index=True),
            sa.Column("category", sa.String(length=50), nullable=False, index=True),
            sa.Column("model_name", sa.String(length=100), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("category", "model_name", name="uq_device_model_catalog_category_model"),
        )

    # ---------------- 3. Buat tabel ticket_spareparts kalau belum ada ----------------
    if "ticket_spareparts" not in existing_tables:
        op.create_table(
            "ticket_spareparts",
            sa.Column("id", sa.Integer(), primary_key=True, index=True),
            sa.Column("ticket_id", sa.Integer(), sa.ForeignKey("service_tickets.id"), nullable=False),
            sa.Column("slot_no", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=150), nullable=True),
            sa.Column("quantity", sa.Integer(), nullable=True),
            sa.Column("code", sa.String(length=50), nullable=True),
            sa.Column("price", sa.Float(), nullable=True),
            sa.UniqueConstraint("ticket_id", "slot_no", name="uq_ticket_spareparts_ticket_slot"),
        )


def downgrade():
    # Sengaja TIDAK diimplementasikan detail. Downgrade otomatis (drop column/table)
    # berisiko menghapus data yang sudah terisi di kolom/tabel baru ini. Kalau suatu
    # saat benar-benar perlu rollback, lakukan manual dengan hati-hati dan backup dulu.
    pass
