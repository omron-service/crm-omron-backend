# Digunakan oleh Alembic Migration untuk mengenali seluruh Model DB.
#
# PENTING: Base di sini berasal dari app.db.session (satu-satunya sumber Base
# di seluruh project). Setiap model yang boleh dikenali Alembic HARUS diimpor
# di sini, dan HANYA SEKALI - jangan ada dua class dengan __tablename__ yang
# sama dari file berbeda (itu penyebab error "Table 'X' is already defined").
from app.db.session import Base
from app.models.enums import LocationType, UserRole, TicketStatus, PaymentStatusEnum, MutationStatus
from app.models.user_location import Location
from app.models.service import DeviceCategory, DeviceModel
from app.models.inventory import SparePart, StockInventory, StockMutation
from app.models.schema import ServiceTicket, User, LocationCounter, DeviceModelCatalog, TicketSparePart

__all__ = [
    "Base",
    "Location",
    "User",
    "DeviceCategory",
    "DeviceModel",
    "ServiceTicket",
    "SparePart",
    "StockInventory",
    "StockMutation",
    "LocationCounter",
    "DeviceModelCatalog",
    "TicketSparePart",
]