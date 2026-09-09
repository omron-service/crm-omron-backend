from app.db.session import Base
from app.models.enums import LocationType, UserRole, TicketStatus, PaymentStatusEnum, MutationStatus
from app.models.user_location import Location
from app.models.service import DeviceCategory, DeviceModel
from app.models.inventory import SparePart, StockInventory, StockMutation
# ServiceTicket, User, dan LocationCounter yang SUNGGUHAN (dipakai oleh
# seluruh sistem auth & ticketing yang sudah berjalan) ada di schema.py -
# WAJIB diimpor di sini juga supaya Alembic/create_all melihat semuanya
# dalam satu metadata yang sama, tanpa duplikat nama tabel.
from app.models.schema import (
    ServiceTicket, User, LocationCounter, DeviceModelCatalog, TicketSparePart,
    PartCatalog, PartStock, PartStockMovement, PartStockOpname,
    BranchCatalog, PickupCenterCatalog, TicketBillingItem, DocumentCounter,
)

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
    "PartCatalog",
    "PartStock",
    "PartStockMovement",
    "PartStockOpname",
    "BranchCatalog",
    "PickupCenterCatalog",
    "TicketBillingItem",
    "DocumentCounter",
]