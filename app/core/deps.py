from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.security import decode_access_token
from app.models.schema import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Sesi tidak valid atau sudah kedaluwarsa. Silakan login kembali.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        raise credentials_error

    try:
        user_id = int(payload["sub"])
    except (TypeError, ValueError):
        raise credentials_error

    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_active:
        raise credentials_error
    return user


def require_role(*allowed_roles: str):
    """Depends(require_role("superadmin")) -> hanya role tsb yang boleh lewat."""

    def _checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Anda tidak memiliki izin untuk mengakses resource ini.",
            )
        return current_user

    return _checker


def require_department_access(current_user: User, srv_type: str) -> None:
    """
    Superadmin & Admin: bebas akses semua lokasi (pusat/cabang/pickup) - role
    "admin" SENGAJA disamakan dgn superadmin di sini (akses data penuh),
    bedanya HANYA di menu Setting (lihat require_role("superadmin") yang
    tetap ketat khusus superadmin di endpoint Kelola User/Model Alat/Cabang/
    Pickup Center - admin TIDAK diberi akses ke situ).
    Staff    : HANYA boleh akses lokasi sesuai `department` miliknya sendiri.

    Dipanggil manual di dalam body endpoint (bukan sebagai Depends bawaan)
    karena srv_type baru diketahui setelah request body/path di-parse.
    Ini mencegah staff cabang membuat/melihat tiket di data pusat (atau
    sebaliknya) meskipun mereka memanggil API langsung tanpa lewat UI.
    """
    if current_user.role in ("superadmin", "admin"):
        return
    if current_user.department != srv_type:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Akun Anda terdaftar di departemen '{current_user.department}', "
                f"tidak diizinkan mengakses data lokasi '{srv_type}'."
            ),
        )
