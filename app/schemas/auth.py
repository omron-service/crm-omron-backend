from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel, EmailStr, Field


class BootstrapIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    department: Optional[str] = None


class UserCreateIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str
    role: Literal["staff", "admin", "superadmin"] = "staff"
    department: Optional[Literal["pusat", "cabang", "pickup"]] = None


class UserUpdateIn(BaseModel):
    """
    Dipakai tombol Edit di Kelola User. `password` OPSIONAL - kosongkan
    kalau tidak mau mengubah password user tsb (isi hanya kalau memang mau
    di-reset ke password baru).
    """
    email: EmailStr
    full_name: str
    role: Literal["staff", "admin", "superadmin"]
    department: Optional[Literal["pusat", "cabang", "pickup"]] = None
    password: Optional[str] = Field(default=None, min_length=8)


class UserOut(BaseModel):
    id: int
    email: EmailStr
    full_name: str
    role: str
    department: Optional[str] = None
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True
