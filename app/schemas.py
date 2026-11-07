from datetime import datetime
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
import re
import html

from app.models import IncidentPriority, IncidentStatus, Role


# XSS protection: comprehensive regex to detect dangerous HTML/JS patterns
# Note: Input validation is a defense-in-depth measure. Primary XSS protection
# should be output encoding (handled by templates/front-end).
XSS_PATTERNS = [
    # Script tags and variants
    r'(?i)<script\b[^>]*>.*?</script>',  # <script> tags (case insensitive)
    r'(?i)<script\b[^>]*>',  # Unclosed script tags
    # Event handlers (onload, onerror, onclick, etc.)
    r'(?i)\bon\w+\s*=',  # Event handlers like onclick=, onload=, onerror=
    # Dangerous tags
    r'(?i)<iframe\b',  # iframe tags
    r'(?i)<object\b',  # object tags
    r'(?i)<embed\b',  # embed tags
    r'(?i)<link\b',  # link tags
    r'(?i)<meta\b',  # meta tags
    r'(?i)<style\b',  # style tags
    r'(?i)<base\b',  # base tags (can hijack relative URLs)
    r'(?i)<form\b',  # form tags (can be used for phishing)
    r'(?i)<input\b',  # input tags
    r'(?i)<textarea\b',  # textarea tags
    r'(?i)<select\b',  # select tags
    r'(?i)<button\b',  # button tags
    # Dangerous protocols
    r'(?i)javascript:',  # javascript: protocol
    r'(?i)vbscript:',  # vbscript: protocol
    r'(?i)data:',  # data: protocol (can contain scripts)
    r'(?i)blob:',  # blob: protocol
    r'(?i)filesystem:',  # filesystem: protocol
    # CSS-based attacks
    r'(?i)expression\s*\(',  # CSS expression()
    r'(?i)behaviour\s*:',  # CSS behaviour (IE)
    r'(?i)-moz-binding\s*:',  # Mozilla binding
    r'(?i)@import\s+["\']?javascript:',  # CSS @import javascript
    # SVG-based attacks
    r'(?i)<svg\b',  # SVG tags
    r'(?i)<animate\b',  # SVG animate
    r'(?i)<set\b',  # SVG set
    # Other dangerous patterns
    r'(?i)<img\b[^>]*onerror\s*=',  # img onerror
    r'(?i)<video\b[^>]*onerror\s*=',  # video onerror
    r'(?i)<audio\b[^>]*onerror\s*=',  # audio onerror
    r'(?i)<details\b[^>]*ontoggle\s*=',  # details ontoggle
    r'(?i)<marquee\b[^>]*onstart\s*=',  # marquee onstart
    # Template injection patterns
    r'\{\{.*\}\}',  # Double curly braces (template engines)
    r'\$\{.*\}',  # Dollar curly braces (JS templates)
    r'<%.*%>',  # ASP/JSP tags
    # Encoded variants (common bypasses)
    r'(?i)<script',  # HTML encoded <script
    r'(?i)<iframe',  # HTML encoded <iframe
    r'(?i)%3cscript',  # URL encoded <script
    r'(?i)%3ciframe',  # URL encoded <iframe
]


def validate_no_xss(value: str, field_name: str) -> str:
    """Validate that a string doesn't contain XSS patterns"""
    for pattern in XSS_PATTERNS:
        if re.search(pattern, value):
            # Log the attempt for security monitoring
            raise ValueError(f'{field_name} contains potentially dangerous content')
    return value


def sanitize_html(value: str) -> str:
    """Sanitize HTML by escaping special characters for safe output"""
    return html.escape(value, quote=True)


class UserCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

    @field_validator('password')
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        """Validate password has uppercase, lowercase, digit, and special char"""
        if not re.search(r'[a-z]', v):
            raise ValueError('Password must contain at least one lowercase letter')
        if not re.search(r'[A-Z]', v):
            raise ValueError('Password must contain at least one uppercase letter')
        if not re.search(r'\d', v):
            raise ValueError('Password must contain at least one digit')
        if not re.search(r'[@$!%*?&]', v):
            raise ValueError('Password must contain at least one special character (@$!%*?&)')
        return v

    @field_validator('name')
    @classmethod
    def validate_name_no_xss(cls, v: str) -> str:
        return validate_no_xss(v, 'name')


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

    @field_validator('title')
    @classmethod
    def validate_title_no_xss(cls, v: str) -> str:
        return validate_no_xss(v, 'title')

    @field_validator('description')
    @classmethod
    def validate_description_no_xss(cls, v: str) -> str:
        return validate_no_xss(v, 'description')

    @field_validator('category')
    @classmethod
    def validate_category_no_xss(cls, v: str) -> str:
        value = validate_no_xss(v, 'category')
        if value.strip().lower() != 'medical':
            raise ValueError('Only medical incidents are supported')
        return 'Medical'

    @field_validator('location')
    @classmethod
    def validate_location_no_xss(cls, v: str) -> str:
        return validate_no_xss(v, 'location')


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
