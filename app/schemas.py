from datetime import datetime
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models import IncidentPriority, IncidentStatus, Role


class UserCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


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
    token_type: str = "bearer"


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
