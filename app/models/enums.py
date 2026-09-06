import enum

class LocationType(str, enum.Enum):
    PUSAT = "PUSAT"
    CABANG = "CABANG"
    PICKUP_CENTER = "PICKUP_CENTER"
    GUDANG_UTAMA = "GUDANG_UTAMA"

class UserRole(str, enum.Enum):
    SUPER_ADMIN = "SUPER_ADMIN"
    BRANCH_ADMIN = "BRANCH_ADMIN"
    TECHNICIAN = "TECHNICIAN"

class TicketStatus(str, enum.Enum):
    RECEIVED = "RECEIVED"
    DIAGNOSING = "DIAGNOSING"
    REPAIRING = "REPAIRING"
    COMPLETED = "COMPLETED"

class PaymentStatusEnum(str, enum.Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    WAIVED_WARRANTY = "WAIVED_WARRANTY"

class MutationStatus(str, enum.Enum):
    REQUESTED = "REQUESTED"
    IN_TRANSIT = "IN_TRANSIT"
    RECEIVED = "RECEIVED"
    REJECTED = "REJECTED"