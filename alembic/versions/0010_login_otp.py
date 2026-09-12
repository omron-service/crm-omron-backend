"""Tambah tabel login_otp_codes untuk 2FA (OTP via email, khusus superadmin).

Revision ID: 0010_login_otp
Revises: 0009_paid_at_field
Create Date: 2026-09-10
"""
from alembic import op
import sqlalchemy as sa

revision = "0010_login_otp"
down_revision = "0009_paid_at_field"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "login_otp_codes" not in inspector.get_table_names():
        op.create_table(
            "login_otp_codes",
            sa.Column("id", sa.Integer(), primary_key=True, index=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("pre_auth_token", sa.String(length=100), nullable=False),
            sa.Column("code_hash", sa.String(length=255), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("consumed", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_login_otp_codes_pre_auth_token", "login_otp_codes", ["pre_auth_token"], unique=True)


def downgrade():
    pass
