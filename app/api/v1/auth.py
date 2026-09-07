from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.security import hash_password, verify_password, create_access_token
from app.core.deps import get_current_user, require_role
from app.models.schema import User
from app.schemas.auth import BootstrapIn, LoginIn, Token, UserCreateIn, UserOut

router = APIRouter(prefix="/api/v1/auth", tags=["Auth"])
admin_users_router = APIRouter(prefix="/api/v1/admin/users", tags=["Admin - Kelola User"])


@router.get("/bootstrap-status")
def bootstrap_status(db: Session = Depends(get_db)):
    """Endpoint publik ringan agar UI tahu harus menampilkan form 'Setup Awal' atau 'Login'."""
    needs_bootstrap = db.query(User).first() is None
    return {"needs_bootstrap": needs_bootstrap}


@router.post("/bootstrap", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def bootstrap_superadmin(data: BootstrapIn, db: Session = Depends(get_db)):
    """
    Setup akun Super Admin PERTAMA KALI sistem dipakai.

    Hanya bisa berhasil selama tabel `users` masih KOSONG. Begitu ada satu
    user saja di database, endpoint ini otomatis terkunci selamanya (403) -
    jadi tidak bisa disalahgunakan orang lain untuk membuat superadmin baru
    diam-diam setelah sistem berjalan.
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
def login(data: LoginIn, db: Session = Depends(get_db)):
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
