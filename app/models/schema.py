from sqlalchemy import Column, Integer, String, Text, DateTime, Float, Boolean, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime

# PENTING: Base TIDAK dibuat di sini lagi. Base yang sebenarnya sekarang hidup
# di app/db/session.py, dipakai bersama oleh SEMUA file model di project ini
# (schema.py, user_location.py, service.py, inventory.py) supaya tidak ada
# dua metadata terpisah yang bentrok satu sama lain.
from app.db.session import Base


class ServiceTicket(Base):
    """
    TIDAK ADA KOLOM LAMA YANG DIHAPUS ATAU DIUBAH DI SINI.
    Semua kolom tambahan bersifat nullable, jadi baris data lama yang sudah
    ada di database tetap valid tanpa perlu diubah.
    """
    __tablename__ = "service_tickets"
    id = Column(Integer, primary_key=True, index=True)
    ticket_number = Column(String(50), unique=True, index=True, nullable=False)

    # Kategori Lokasi Input - SATU tiket HANYA punya SATU service_type, ditentukan
    # sekali saat create dan tidak pernah ditulis ulang ke lokasi lain.
    service_type = Column(String(20), index=True, default="pusat")  # pusat, cabang, pickup
    created_by_location = Column(String(50), index=True, default="PUSAT_JAKARTA")

    # BARU: jejak siapa (user mana) yang membuat tiket ini. Nullable agar
    # baris lama (dibuat sebelum ada sistem login) tetap valid.
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_by = relationship("User", backref="tickets")

    # Data Pelanggan
    customer_name = Column(String(100), nullable=False)
    instansi_name = Column(String(150), nullable=True)  # BARU: Nama Instansi
    customer_phone = Column(String(30), nullable=False)  # No. HP/WA 1
    customer_phone_2 = Column(String(30), nullable=True)  # No. HP/WA 2
    customer_address = Column(Text, nullable=True)
    province = Column(String(50), nullable=True)
    city = Column(String(50), nullable=True)
    branch_or_point = Column(String(100), nullable=True)

    # Tanggal proses servis
    received_date = Column(DateTime, nullable=True)  # BARU: tanggal alat diterima
    completed_date = Column(DateTime, nullable=True)  # BARU: tanggal alat selesai

    # Data Produk
    product_category = Column(String(50), nullable=True)
    device_model = Column(String(100), nullable=False)
    serial_number = Column(String(50), nullable=True)
    accessories = Column(String(150), nullable=True)
    warranty_status = Column(String(30), default="Out of Warranty")
    warranty_period = Column(String(20), nullable=True)
    product_origin = Column(String(50), nullable=True)

    # Data Servis
    complaint = Column(Text, nullable=True)
    technician_analysis = Column(Text, nullable=True)
    symptom_code = Column(String(30), nullable=True)
    leadtime_days = Column(Integer, default=1)
    notes = Column(Text, nullable=True)
    remarks = Column(String(100), nullable=True)
    status = Column(String(50), default="Diterima")

    # BARU: Preferensi notifikasi (masing-masing independen: boleh keduanya,
    # salah satu, atau tidak sama sekali)
    notif_receipt_whatsapp = Column(Boolean, default=False, nullable=False)
    notif_receipt_email = Column(Boolean, default=False, nullable=False)
    notif_report_whatsapp = Column(Boolean, default=False, nullable=False)
    notif_report_email = Column(Boolean, default=False, nullable=False)

    # Payment
    total_price = Column(Float, default=0.0)
    payment_code = Column(String(50), nullable=True)
    payment_status = Column(String(30), default="Belum Lunas")

    # BARU: Data untuk keperluan pembayaran (Tab Status Payment Service)
    customer_id_number = Column(String(30), nullable=True)  # NIK atau NPWP pelanggan
    payment_method = Column(String(50), nullable=True)      # kanal yang dipilih, mis. VIRTUAL_ACCOUNT_BCA
    payment_url = Column(String(500), nullable=True)        # link halaman pembayaran DOKU
    payment_expired_at = Column(DateTime, nullable=True)    # kapan kode bayar/VA ini kedaluwarsa

    # BARU: Data khusus dokumen Penawaran Harga & Invoice (TIDAK mengubah data
    # asli tiket - mis. invoice_owner_name terpisah dari customer_name)
    invoice_owner_name = Column(String(150), nullable=True)  # "Nama Pemilik untuk Invoice"
    customer_email = Column(String(200), nullable=True)
    invoice_address = Column(Text, nullable=True)             # alamat khusus dokumen (override customer_address)
    ppn_free = Column(Boolean, default=False, nullable=False)          # "Bebas PPN"
    use_manual_price_breakdown = Column(Boolean, default=False, nullable=False)  # toggle "Input Harga Manual"
    pph23_amount = Column(Float, nullable=True)
    admin_bank_fee = Column(Float, nullable=True)
    invoice_number = Column(String(50), nullable=True)    # "098/INV/MD/2026" - dibuat sekali, permanen
    quotation_number = Column(String(50), nullable=True)  # "067/SPH/MD/2026" - dibuat sekali, permanen

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    spareparts = relationship(
        "TicketSparePart", back_populates="ticket", order_by="TicketSparePart.slot_no"
    )
    billing_items = relationship(
        "TicketBillingItem", back_populates="ticket", order_by="TicketBillingItem.sequence",
        cascade="all, delete-orphan",
    )


class TicketBillingItem(Base):
    """
    Daftar "Item Layanan" untuk dokumen Penawaran Harga / Invoice - SENGAJA
    terpisah dari TicketSparePart (yang untuk keperluan servis fisik & stok),
    supaya satu tiket bisa menagih LEBIH DARI SATU alat sekaligus (mis. Item #1
    = alat pada tiket ini, Item #2 = alat lain yang referensinya ke tiket lain
    lewat ref_ticket_number) tanpa mempengaruhi data servis/stok yang sudah ada.
    """
    __tablename__ = "ticket_billing_items"

    id = Column(Integer, primary_key=True, index=True)
    ticket_id = Column(Integer, ForeignKey("service_tickets.id"), nullable=False)
    sequence = Column(Integer, nullable=False, default=1)  # urutan tampil (1, 2, 3, ...)

    service_type = Column(String(20), default="Perbaikan")  # "Perbaikan" atau "Kalibrasi"
    product_category = Column(String(50), nullable=True)
    device_model = Column(String(100), nullable=True)
    serial_number = Column(String(50), nullable=True)
    description = Column(Text, nullable=True)  # keluhan/kerusakan, utk baris "Unit ... rusak"
    quantity = Column(Integer, default=1)
    price = Column(Float, default=0.0)  # harga satuan
    ref_ticket_number = Column(String(30), nullable=True)  # diisi kalau item ini menarik data dari tiket lain

    ticket = relationship("ServiceTicket", back_populates="billing_items")


class DocumentCounter(Base):
    """Nomor urut dokumen Invoice/SPH, per jenis dan per tahun (reset tiap tahun baru)."""
    __tablename__ = "document_counters"

    id = Column(Integer, primary_key=True, index=True)
    doc_type = Column(String(10), nullable=False)  # "INV" atau "SPH"
    year = Column(Integer, nullable=False)
    last_number = Column(Integer, default=0, nullable=False)

    __table_args__ = (UniqueConstraint("doc_type", "year", name="uq_doc_counter_type_year"),)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(150), unique=True, index=True, nullable=False)
    full_name = Column(String(150), nullable=False)
    password_hash = Column(String(255), nullable=False)

    # "superadmin" = akses penuh semua lokasi + bisa kelola user lain
    # "staff"      = akses terbatas HANYA ke lokasi sesuai `department`
    role = Column(String(20), nullable=False, default="staff")

    # Departemen/lokasi kerja: "pusat", "cabang", atau "pickup".
    # NULL untuk superadmin (superadmin tidak dibatasi lokasi manapun).
    department = Column(String(20), nullable=True)

    is_active = Column(Boolean, default=True, nullable=False)  # nonaktifkan akun = soft, bukan delete
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class LocationCounter(Base):
    """
    Counter nomor urut tiket PER LOKASI, disimpan di tabel terpisah dan di-lock
    saat increment (SELECT ... FOR UPDATE). Ini mencegah race condition yang bisa
    menghasilkan dua tiket dengan nomor sama saat dua orang input bersamaan
    di lokasi yang sama.
    """
    __tablename__ = "location_counters"
    __table_args__ = (UniqueConstraint("service_type", name="uq_location_counters_service_type"),)

    id = Column(Integer, primary_key=True, index=True)
    service_type = Column(String(20), nullable=False, index=True)
    last_number = Column(Integer, nullable=False, default=0)


class DeviceModelCatalog(Base):
    """
    Katalog Model Alat per Kategori Produk, dikelola oleh Super Admin lewat
    menu "Kelola Model Alat". Ini membuat dropdown "Model Alat" di form input
    tiket otomatis terisi sesuai Kategori Produk yang dipilih, dan bisa terus
    ditambah tanpa perlu ubah kode/deploy ulang.
    """
    __tablename__ = "device_model_catalog"
    __table_args__ = (
        UniqueConstraint("category", "model_name", name="uq_device_model_catalog_category_model"),
    )

    id = Column(Integer, primary_key=True, index=True)
    category = Column(String(50), nullable=False, index=True)  # harus salah satu dari PRODUCT_CATEGORIES
    model_name = Column(String(100), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)  # nonaktifkan = soft, bukan delete
    created_at = Column(DateTime, default=datetime.utcnow)


class TicketSparePart(Base):
    """
    Baris sparepart yang dipakai untuk satu tiket servis. Maksimal 3 slot per
    tiket sesuai form (Sparepart 1/2/3), disimpan sebagai tabel terpisah
    (bukan kolom pipih) supaya lebih rapi dan gampang dikembangkan nanti
    (mis. kalau suatu saat butuh lebih dari 3 sparepart).
    """
    __tablename__ = "ticket_spareparts"
    __table_args__ = (
        UniqueConstraint("ticket_id", "slot_no", name="uq_ticket_spareparts_ticket_slot"),
    )

    id = Column(Integer, primary_key=True, index=True)
    ticket_id = Column(Integer, ForeignKey("service_tickets.id"), nullable=False)
    slot_no = Column(Integer, nullable=False)  # 1, 2, atau 3
    name = Column(String(150), nullable=True)
    quantity = Column(Integer, nullable=True)
    code = Column(String(50), nullable=True)
    price = Column(Float, nullable=True)

    ticket = relationship("ServiceTicket", back_populates="spareparts")


# ==================== INVENTORY PART (Stok Sparepart Pusat & Cabang) ====================
# Nama class sengaja PartCatalog/PartStock/dst (bukan SparePart/StockInventory) supaya
# TIDAK bentrok dengan class lama di app/models/inventory.py yang sudah ada sebelumnya
# (SparePart, StockInventory, StockMutation) - keduanya sekarang hidup berdampingan,
# tidak saling menghapus/mengganggu.

class PartCatalog(Base):
    """Katalog induk sparepart (kode + nama), dibuat otomatis begitu kode sparepart
    pertama kali dipakai di salah satu form pergerakan stok."""
    __tablename__ = "part_catalog"
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(50), unique=True, index=True, nullable=False)
    name = Column(String(150), nullable=True)
    unit_price = Column(Float, nullable=True, default=0.0)
    status = Column(String(20), nullable=True, default="Active")  # "Active" atau "Discontinue"
    model_alat = Column(String(150), nullable=True)  # Model alat terkait sparepart ini (bebas teks)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PartStock(Base):
    """Jumlah stok TERKINI per sparepart per lokasi ("pusat" atau "cabang")."""
    __tablename__ = "part_stock"
    __table_args__ = (UniqueConstraint("part_id", "location", name="uq_part_stock_part_location"),)

    id = Column(Integer, primary_key=True, index=True)
    part_id = Column(Integer, ForeignKey("part_catalog.id"), nullable=False)
    location = Column(String(20), nullable=False, index=True)  # "pusat" atau "cabang"
    quantity = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    part = relationship("PartCatalog")


class PartStockMovement(Base):
    """
    Riwayat SETIAP pergerakan stok (item masuk/keluar), sumber data untuk laporan
    Excel "Total Kirim ke Cabang", "Total Terpakai", dll. TIDAK PERNAH dihapus -
    ini adalah jejak audit permanen.
    movement_type yang valid: terima_gudang, kirim_ke_cabang, terima_dari_cabang,
    terpakai_pusat, terima_dari_pusat, kirim_balik_ke_pusat, terpakai_cabang.
    """
    __tablename__ = "part_stock_movements"
    id = Column(Integer, primary_key=True, index=True)
    part_id = Column(Integer, ForeignKey("part_catalog.id"), nullable=False)
    location = Column(String(20), nullable=False, index=True)
    movement_type = Column(String(30), nullable=False, index=True)
    quantity = Column(Integer, nullable=False)
    note = Column(String(255), nullable=True)
    # BARU: konteks tambahan sesuai format Excel Terima/Kirim Stok.
    device_model = Column(String(100), nullable=True)      # "Model Alat" - sparepart ini untuk model alat apa
    part_status = Column(String(50), nullable=True)        # "Status" - kondisi/status sparepart (bebas isi)
    related_branch = Column(String(150), nullable=True)    # "Nama Cabang Asal"/"Nama Cabang Tujuan" -
                                                             # WAJIB diisi utk kirim_ke_cabang & terima_dari_cabang
    performed_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    part = relationship("PartCatalog")
    performed_by = relationship("User")


class PartStockOpname(Base):
    """Hasil stok opname (hitung fisik) per sparepart per lokasi. Menyimpan jumlah
    sistem SEBELUM opname, jumlah hasil hitung fisik, dan selisihnya - untuk audit,
    tidak pernah ditimpa/dihapus."""
    __tablename__ = "part_stock_opname"
    id = Column(Integer, primary_key=True, index=True)
    part_id = Column(Integer, ForeignKey("part_catalog.id"), nullable=False)
    location = Column(String(20), nullable=False, index=True)
    system_quantity = Column(Integer, nullable=False)
    counted_quantity = Column(Integer, nullable=False)
    difference = Column(Integer, nullable=False)
    note = Column(String(255), nullable=True)
    performed_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    part = relationship("PartCatalog")
    performed_by = relationship("User")


# ==================== KELOLA CABANG & PICKUP CENTER (Master Data) ====================
# CATATAN: tabel ini murni master data (daftar cabang/pickup center yang bisa
# ditambah/edit/nonaktifkan lewat menu Setting). BELUM dihubungkan ke alur
# pembuatan tiket/inventory yang sudah ada (yang masih pakai service_type
# "pusat"/"cabang"/"pickup" sebagai satu bucket per lokasi) - kalau nanti mau
# tiket/inventory memilih cabang/pickup SPESIFIK dari daftar ini, itu perlu
# perubahan lanjutan tersendiri.

class BranchCatalog(Base):
    """Master data Cabang (OEC-Medan, OEC-Bandung, dst)."""
    __tablename__ = "branch_catalog"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False)          # Nama Cabang, mis. "OEC-Medan"
    code = Column(String(20), unique=True, index=True, nullable=False)  # Kode Store, mis. "MDN"
    handled_by = Column(String(150), nullable=True)      # Handle by, mis. "Mitracare"
    city = Column(String(100), nullable=True)            # Kota
    address = Column(Text, nullable=True)                # Alamat lengkap
    is_active = Column(Boolean, default=True, nullable=False)  # nonaktifkan = soft, bukan delete
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PickupCenterCatalog(Base):
    """Master data Pickup Center (mis. jaringan Apotek Alpro yang jadi drop-off point)."""
    __tablename__ = "pickup_center_catalog"

    id = Column(Integer, primary_key=True, index=True)
    store_long_code = Column(String(50), unique=True, index=True, nullable=False)  # mis. "0001 - JKJSTT1"
    store_name = Column(String(200), nullable=False)     # Store Name
    store_address = Column(Text, nullable=True)          # Store Address
    city = Column(String(100), nullable=True)            # City
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
