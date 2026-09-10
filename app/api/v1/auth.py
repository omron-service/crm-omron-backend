from typing import List
import hashlib
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.security import hash_password, verify_password, create_access_token
from app.core.deps import get_current_user, require_role
from app.core.limiter import limiter
from app.models.schema import User, LoginOtpCode
from app.schemas.auth import (
    BootstrapIn, LoginIn, Token, UserCreateIn, UserUpdateIn, UserOut,
    LoginResponse, VerifyOtpIn, ResendOtpIn,
)

router = APIRouter(prefix="/api/v1/auth", tags=["Auth"])
admin_users_router = APIRouter(prefix="/api/v1/admin/users", tags=["Admin - Kelola User"])

OTP_EXPIRY_MINUTES = 5
OTP_MAX_ATTEMPTS = 5
# Role yang WAJIB verifikasi OTP email setelah password benar - SAAT INI
# cuma superadmin (keputusan bisnis saat ini), staff & admin tetap login
# biasa 1 langkah seperti sebelumnya.
OTP_REQUIRED_ROLES = {"superadmin"}


def _hash_otp_code(code: str, pre_auth_token: str) -> str:
    # Diikat dgn pre_auth_token supaya hash kode yg sama utk sesi login
    # berbeda TETAP berbeda satu sama lain (mencegah rainbow-table sederhana).
    return hashlib.sha256(f"{code}:{pre_auth_token}".encode()).hexdigest()


def _mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    masked_local = local[:2] + "*" * max(len(local) - 2, 1)
    return f"{masked_local}@{domain}"


def _create_and_send_otp(db: Session, user: User) -> str:
    from app.services.email_otp import send_otp_email
    pre_auth_token = secrets.token_urlsafe(32)
    code = f"{secrets.randbelow(1000000):06d}"
    otp_row = LoginOtpCode(
        user_id=user.id,
        pre_auth_token=pre_auth_token,
        code_hash=_hash_otp_code(code, pre_auth_token),
        expires_at=datetime.utcnow() + timedelta(minutes=OTP_EXPIRY_MINUTES),
    )
    db.add(otp_row)
    db.commit()
    send_otp_email(user.email, code, user.full_name)
    return pre_auth_token


@router.get("/bootstrap-status")
def bootstrap_status(db: Session = Depends(get_db)):
    """Endpoint publik ringan agar UI tahu harus menampilkan form 'Setup Awal' atau 'Login'."""
    needs_bootstrap = db.query(User).first() is None
    return {"needs_bootstrap": needs_bootstrap}


@router.post("/bootstrap", response_model=UserOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
def bootstrap_superadmin(request: Request, data: BootstrapIn, db: Session = Depends(get_db)):
    """
    Setup akun Super Admin PERTAMA KALI sistem dipakai.

    Hanya bisa berhasil selama tabel `users` masih KOSONG. Begitu ada satu
    user saja di database, endpoint ini otomatis terkunci selamanya (403) -
    jadi tidak bisa disalahgunakan orang lain untuk membuat superadmin baru
    diam-diam setelah sistem berjalan. Rate limit 5/menit sebagai lapisan
    proteksi tambahan (defense in depth) selama jendela waktu sebelum
    superadmin pertama dibuat.
    """
    if db.query(User).first() is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Sistem sudah memiliki Super Admin. Endpoint bootstrap sudah "
                "dinonaktifkan. Hubungi Super Admin yang ada untuk dibuatkan akun."
            ),
        )

    user = User(
        email=data.email.lower().strip(),
        full_name=data.full_name.strip(),
        password_hash=hash_password(data.password),
        role="superadmin",
        department=None,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=LoginResponse)
@limiter.limit("5/minute")
def login(request: Request, data: LoginIn, db: Session = Depends(get_db)):
    """
    Rate limit 5/menit per alamat IP - mencegah brute force menebak password
    secara otomatis dalam jumlah besar. Pesan error SENGAJA sama persis untuk
    "email tidak ada" maupun "password salah", supaya tidak bisa dipakai untuk
    menebak email mana saja yang terdaftar di sistem (user enumeration).

    Untuk role di OTP_REQUIRED_ROLES (saat ini: superadmin), setelah password
    benar TIDAK langsung dapat token - kode OTP dikirim ke email dulu, token
    baru terbit setelah verifikasi lewat /auth/verify-otp berhasil.
    """
    invalid_cred_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Email atau password salah.",
    )

    user = db.query(User).filter(User.email == data.email.lower().strip()).first()
    if not user or not user.is_active:
        raise invalid_cred_error
    if not verify_password(data.password, user.password_hash):
        raise invalid_cred_error

    if user.role in OTP_REQUIRED_ROLES:
        from app.services.email_otp import OtpEmailConfigError, OtpEmailSendError
        try:
            pre_auth_token = _create_and_send_otp(db, user)
        except OtpEmailConfigError as e:
            raise HTTPException(status_code=503, detail=str(e))
        except OtpEmailSendError as e:
            raise HTTPException(status_code=502, detail=str(e))
        return LoginResponse(otp_required=True, pre_auth_token=pre_auth_token, email_hint=_mask_email(user.email))

    token = create_access_token(
        data={"sub": str(user.id), "role": user.role, "department": user.department}
    )
    return LoginResponse(
        otp_required=False,
        token=Token(access_token=token, role=user.role, department=user.department),
    )


@router.post("/verify-otp", response_model=Token)
@limiter.limit("10/minute")
def verify_otp(request: Request, data: VerifyOtpIn, db: Session = Depends(get_db)):
    """
    Langkah ke-2 login superadmin - cocokkan kode OTP dari email dengan yang
    tersimpan (ter-hash). Maks 5x percobaan salah per kode sebelum kode itu
    otomatis dianggap gugur (harus login ulang dari awal, bukan cuma minta
    kode baru) - mencegah brute force menebak 6 digit kode.
    """
    generic_error = HTTPException(status_code=401, detail="Kode OTP tidak valid atau sudah kedaluwarsa.")

    otp_row = (
        db.query(LoginOtpCode)
        .filter(LoginOtpCode.pre_auth_token == data.pre_auth_token, LoginOtpCode.consumed.is_(False))
        .first()
    )
    if not otp_row:
        raise generic_error
    if otp_row.expires_at < datetime.utcnow():
        otp_row.consumed = True
        db.commit()
        raise generic_error
    if otp_row.attempts >= OTP_MAX_ATTEMPTS:
        otp_row.consumed = True
        db.commit()
        raise HTTPException(status_code=401, detail="Terlalu banyak percobaan salah. Silakan login ulang dari awal.")

    expected_hash = _hash_otp_code(data.code.strip(), data.pre_auth_token)
    if expected_hash != otp_row.code_hash:
        otp_row.attempts += 1
        db.commit()
        sisa = OTP_MAX_ATTEMPTS - otp_row.attempts
        raise HTTPException(status_code=401, detail=f"Kode OTP salah. Sisa percobaan: {sisa}.")

    otp_row.consumed = True
    db.commit()

    user = db.query(User).filter(User.id == otp_row.user_id).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Akun tidak aktif.")

    token = create_access_token(
        data={"sub": str(user.id), "role": user.role, "department": user.department}
    )
    return Token(access_token=token, role=user.role, department=user.department)


@router.post("/resend-otp")
@limiter.limit("3/minute")
def resend_otp(request: Request, data: ResendOtpIn, db: Session = Depends(get_db)):
    """Kirim ulang kode OTP baru (kode lama otomatis batal), maks 3x/menit per IP."""
    otp_row = (
        db.query(LoginOtpCode)
        .filter(LoginOtpCode.pre_auth_token == data.pre_auth_token, LoginOtpCode.consumed.is_(False))
        .first()
    )
    if not otp_row or otp_row.expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Sesi login sudah tidak valid, silakan login ulang dari awal.")

    user = db.query(User).filter(User.id == otp_row.user_id).first()
    if not user:
        raise HTTPException(status_code=400, detail="Sesi login sudah tidak valid, silakan login ulang dari awal.")

    from app.services.email_otp import send_otp_email, OtpEmailConfigError, OtpEmailSendError
    code = f"{secrets.randbelow(1000000):06d}"
    otp_row.code_hash = _hash_otp_code(code, otp_row.pre_auth_token)
    otp_row.expires_at = datetime.utcnow() + timedelta(minutes=OTP_EXPIRY_MINUTES)
    otp_row.attempts = 0
    db.commit()

    try:
        send_otp_email(user.email, code, user.full_name)
    except OtpEmailConfigError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except OtpEmailSendError as e:
        raise HTTPException(status_code=502, detail=str(e))

    return {"status": "success", "message": "Kode OTP baru sudah dikirim ke email Anda."}


@router.get("/me", response_model=UserOut)
def read_current_user(current_user: User = Depends(get_current_user)):
    return current_user


# ---------------- Endpoint khusus Super Admin: kelola user per departemen ----------------

@admin_users_router.post("/", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    data: UserCreateIn,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role("superadmin")),
):
    if db.query(User).filter(User.email == data.email.lower().strip()).first():
        raise HTTPException(status_code=400, detail="Email sudah terdaftar.")

    if data.role == "staff" and not data.department:
        raise HTTPException(
            status_code=400,
            detail="Staff wajib memiliki 'department' (pusat/cabang/pickup).",
        )

    user = User(
        email=data.email.lower().strip(),
        full_name=data.full_name.strip(),
        password_hash=hash_password(data.password),
        role=data.role,
        department=data.department if data.role == "staff" else None,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@admin_users_router.get("/", response_model=List[UserOut])
def list_users(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role("superadmin")),
):
    return db.query(User).order_by(User.id).all()


@admin_users_router.put("/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    data: UserUpdateIn,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role("superadmin")),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User tidak ditemukan.")

    email_normalized = data.email.lower().strip()
    existing = db.query(User).filter(User.email == email_normalized, User.id != user_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email sudah dipakai user lain.")

    if data.role == "staff" and not data.department:
        raise HTTPException(status_code=400, detail="Staff wajib memiliki 'department' (pusat/cabang/pickup).")

    # Mencegah superadmin (termasuk diri sendiri) diturunkan rolenya kalau itu
    # SATU-SATUNYA superadmin yang tersisa - supaya tidak ada yang terkunci
    # dari akses Kelola User selamanya.
    if user.role == "superadmin" and data.role != "superadmin":
        remaining_superadmins = db.query(User).filter(User.role == "superadmin", User.id != user_id).count()
        if remaining_superadmins == 0:
            raise HTTPException(status_code=400, detail="Tidak bisa mengubah role - ini Super Admin TERAKHIR yang tersisa.")

    user.email = email_normalized
    user.full_name = data.full_name.strip()
    user.role = data.role
    user.department = data.department if data.role == "staff" else None
    if data.password:
        user.password_hash = hash_password(data.password)

    db.commit()
    db.refresh(user)
    return user


@admin_users_router.patch("/{user_id}/deactivate", response_model=UserOut)
def deactivate_user(
    user_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role("superadmin")),
):
    """
    Menonaktifkan akses login user (soft-disable), BUKAN menghapus user.
    Tiket-tiket yang pernah dibuat user ini (created_by_user_id) tetap utuh
    dan riwayatnya tidak hilang.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User tidak ditemukan.")
    if user.role == "superadmin" and _admin.id == user.id:
        raise HTTPException(status_code=400, detail="Tidak bisa menonaktifkan akun Anda sendiri.")
    user.is_active = False
    db.commit()
    db.refresh(user)
    return user


@admin_users_router.patch("/{user_id}/reactivate", response_model=UserOut)
def reactivate_user(
    user_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role("superadmin")),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User tidak ditemukan.")
    user.is_active = True
    db.commit()
    db.refresh(user)
    return user
