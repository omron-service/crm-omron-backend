from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.security import hash_password, verify_password, create_access_token
from app.core.deps import get_current_user, require_role
from app.core.limiter import limiter
from app.models.schema import User
from app.schemas.auth import BootstrapIn, LoginIn, Token, UserCreateIn, UserUpdateIn, UserOut

router = APIRouter(prefix="/api/v1/auth", tags=["Auth"])
admin_users_router = APIRouter(prefix="/api/v1/admin/users", tags=["Admin - Kelola User"])


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


@router.post("/login", response_model=Token)
@limiter.limit("5/minute")
def login(request: Request, data: LoginIn, db: Session = Depends(get_db)):
    """
    Rate limit 5/menit per alamat IP - mencegah brute force menebak password
    secara otomatis dalam jumlah besar. Pesan error SENGAJA sama persis untuk
    "email tidak ada" maupun "password salah", supaya tidak bisa dipakai untuk
    menebak email mana saja yang terdaftar di sistem (user enumeration).
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

    token = create_access_token(
        data={"sub": str(user.id), "role": user.role, "department": user.department}
    )
    return Token(access_token=token, role=user.role, department=user.department)


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
