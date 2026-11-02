from datetime import datetime
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models import IncidentPriority, IncidentStatus, Role


class UserCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

    @field_validator('password')
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        """Validate password has uppercase, lowercase, digit, and special char"""
        import re
        if not re.search(r'[a-z]', v):
            raise ValueError('Password must contain at least one lowercase letter')
        if not re.search(r'[A-Z]', v):
            raise ValueError('Password must contain at least one uppercase letter')
        if not re.search(r'\d', v):
            raise ValueError('Password must contain at least one digit')
        if not re.search(r'[@$!%*?&]', v):
            raise ValueError('Password must contain at least one special character (@$!%*?&)')
        return v


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: int
    name: str
    email: EmailStr
    role: Role
    model_config = ConfigDict(from_attributes=True)


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class IncidentCreate(BaseModel):
    title: str = Field(min_length=3, max_length=150)
    description: str = Field(min_length=5, max_length=5000)
    category: str = Field(min_length=2, max_length=50)
    location: str = Field(min_length=2, max_length=200)
    priority: IncidentPriority = IncidentPriority.medium


class IncidentOut(BaseModel):
    id: int
    title: str
    description: str
    category: str
    location: str
    priority: IncidentPriority
    status: IncidentStatus
    reporter_id: int
    assigned_to: int | None
    image_path: str | None
    created_at: datetime
    assigned_at: datetime | None
    resolved_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class AssignIncident(BaseModel):
    responder_id: int


class UpdateStatus(BaseModel):
    status: IncidentStatus


class IncidentList(BaseModel):
    items: list[IncidentOut]
    total: int
    limit: int
    offset: int
    model_config = ConfigDict(from_attributes=True)
