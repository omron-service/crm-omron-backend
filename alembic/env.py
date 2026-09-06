import os
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context

# Import Base model kamu
from app.db.base import Base

config = context.config

# BACA DATABASE_URL DARI ENVIRONMENT RAILWAY
database_url = os.getenv("DATABASE_URL")
if database_url:
    # Ubah postgres:// jadi postgresql:// jika perlu
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    config.set_main_option("sqlalchemy.url", database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# ... sisa isi alembic/env.py biarkan saja ...