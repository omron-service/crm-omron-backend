import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from passlib.context import CryptContext
from app.db.session import SessionLocal
from app.models import Location, User, DeviceCategory, DeviceModel, SparePart, LocationType, UserRole

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

def seed():
    db = SessionLocal()
    try:
        # 1. Lokasi Awal
        loc_pst = Location(name="SC Pusat Jakarta", code="PST-01", location_type=LocationType.PUSAT)
        loc_cbg = Location(name="SC Cabang Surabaya", code="CBG-SUB", location_type=LocationType.CABANG)
        db.add_all([loc_pst, loc_cbg])
        db.flush()

        # 2. Akun Super Admin
        admin = User(
            email="superadmin@omron.co.id", 
            password_hash=pwd_ctx.hash("AdminOmron2026!"), 
            full_name="Super Admin Omron", 
            role=UserRole.SUPER_ADMIN, 
            location_id=loc_pst.id
        )
        db.add(admin)

        # 3. Master Kategori & Model
        cat = DeviceCategory(name="Tensimeter Digital")
        db.add(cat)
        db.flush()
        mod = DeviceModel(category_id=cat.id, model_name="HEM-7120")
        db.add(mod)

        # 4. Master Spare Part
        sp = SparePart(part_number="PRT-PUMP-01", name="Air Pump Unit", price=150000)
        db.add(sp)

        db.commit()
        print("=== SEEDING DATABASE SUCCESSFUL ===")
    except Exception as e:
        db.rollback()
        print(f"Seeding failed: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    seed()