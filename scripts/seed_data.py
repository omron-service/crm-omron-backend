from app.db.session import SessionLocal
from app.models.enums import LocationType, UserRole
from app.models.user_location import Location, User
from app.models.inventory import SparePart, StockInventory
from app.core.security import get_password_hash

def seed():
    db = SessionLocal()
    try:
        # 1. Seed Locations
        loc_pusat = db.query(Location).filter_map if hasattr(db.query(Location), 'filter_map') else db.query(Location).filter(Location.code == "SC-JKT-01").first()
        if not loc_pusat:
            loc_pusat = Location(name="Omron Service Center Jakarta Pusat", code="SC-JKT-01", type=LocationType.SERVICE_CENTER, address="Jl. Gajah Mada, Jakarta")
            loc_cabang = Location(name="Omron Service Center Surabaya", code="SC-SBY-01", type=LocationType.SERVICE_CENTER, address="Jl. Pemuda, Surabaya")
            db.add_all([loc_pusat, loc_cabang])
            db.commit()
            db.refresh(loc_pusat)
            db.refresh(loc_cabang)

        # 2. Seed Super Admin User
        user = db.query(User).filter(User.email == "superadmin@omron.co.id").first()
        if not user:
            user = User(
                email="superadmin@omron.co.id",
                hashed_password=get_password_hash("AdminOmron2026!"),
                full_name="Super Admin Omron",
                role=UserRole.SUPER_ADMIN,
                location_id=loc_pusat.id
            )
            db.add(user)

        # 3. Seed Spare Parts
        sp1 = db.query(SparePart).filter(SparePart.part_code == "SP-CUFF-HEM").first()
        if not sp1:
            sp1 = SparePart(name="Manset / Cuff Tensimeter Universal", part_code="SP-CUFF-HEM", price=150000.0)
            sp2 = SparePart(name="Mainboard PCB HEM-7120", part_code="PCB-HEM-7120", price=250000.0)
            sp3 = SparePart(name="Sensor Thermometer MC-246", part_code="SNS-MC-246", price=450000.0)
            db.add_all([sp1, sp2, sp3])
            db.commit()
            db.refresh(sp1)

            # Assign Stock
            stk1 = StockInventory(location_id=loc_pusat.id, spare_part_id=sp1.id, quantity=50)
            db.add(stk1)

        db.commit()
        print("--- Database Seeding Berhasil Diselesaikan! ---")
    except Exception as e:
        db.rollback()
        print(f"Error seeding data: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    seed()