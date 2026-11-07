from datetime import datetime
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
import re
import html

from app.core.constants import PASSWORD_SPECIAL_CHARS
from app.models import IncidentPriority, IncidentStatus, Role


# XSS protection: comprehensive regex to detect dangerous HTML/JS patterns
# Note: Input validation is a defense-in-depth measure. Primary XSS protection
# should be output encoding (handled by templates/front-end).
XSS_PATTERNS = [
    # Script tags and variants
    r'(?i)<script\b[^>]*>.*?</script>',  # <script> tags (case insensitive)
    r'(?i)<script\b[^>]*>',  # Unclosed script tags
    r'(?i)</script\b[^>]*>',  # Closing script tags
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
    r'(?i)url\s*\(\s*["\']?javascript:',  # CSS url(javascript:...)
    r'(?i)url\s*\(\s*["\']?data:',  # CSS url(data:...)
    r'(?i)url\s*\(\s*["\']?vbscript:',  # CSS url(vbscript:...)
    # SVG-based attacks
    r'(?i)<svg\b',  # SVG tags
    r'(?i)<animate\b',  # SVG animate
    r'(?i)<set\b',  # SVG set
    r'(?i)<foreignObject\b',  # SVG foreignObject
    r'(?i)<use\b[^>]*xlink:href',  # SVG use with xlink:href
    # Other dangerous patterns
    r'(?i)<img\b[^>]*onerror\s*=',  # img onerror
    r'(?i)<video\b[^>]*onerror\s*=',  # video onerror
    r'(?i)<audio\b[^>]*onerror\s*=',  # audio onerror
    r'(?i)<details\b[^>]*ontoggle\s*=',  # details ontoggle
    r'(?i)<marquee\b[^>]*onstart\s*=',  # marquee onstart
    r'(?i)<body\b[^>]*onload\s*=',  # body onload
    r'(?i)<input\b[^>]*onfocus\s*=',  # input onfocus
    r'(?i)<select\b[^>]*onchange\s*=',  # select onchange
    r'(?i)<textarea\b[^>]*onfocus\s*=',  # textarea onfocus
    r'(?i)<keygen\b',  # keygen tag
    r'(?i)<isindex\b',  # isindex tag
    # Template injection patterns
    r'\{\{.*\}\}',  # Double curly braces (template engines)
    r'\$\{.*\}',  # Dollar curly braces (JS templates)
    r'<%.*%>',  # ASP/JSP tags
    r'#\{.*\}',  # Ruby/Rails template
    # Encoded variants (common bypasses)
    r'(?i)<script',  # HTML encoded <script
    r'(?i)<iframe',  # HTML encoded <iframe
    r'(?i)%3cscript',  # URL encoded <script
    r'(?i)%3ciframe',  # URL encoded <iframe
    # Double/mixed encoding bypasses
    r'(?i)%253cscript',  # Double URL encoded <script
    r'(?i)%253ciframe',  # Double URL encoded <iframe
    r'(?i)<script',  # HTML entity encoded
    r'(?i)<iframe',  # HTML entity encoded
    r'(?i)&lt;script',  # Double HTML entity encoded
    # Unicode/character encoding bypasses
    r'(?i)&#x3c;script',  # Hex entity encoded
    r'(?i)&#60;script',  # Decimal entity encoded
    r'(?i)&#x3c;iframe',  # Hex entity encoded
    r'(?i)&#60;iframe',  # Decimal entity encoded
    # Full-width Unicode variants
    r'(?i)＜script',  # Full-width <
    r'(?i)＞script',  # Full-width >
    r'(?i)＜iframe',  # Full-width <
    # Base64/encoded data URIs with scripts
    r'(?i)data:\s*text/html\s*;\s*base64,',  # Base64 encoded HTML
    r'(?i)data:\s*application/javascript\s*;\s*base64,',  # Base64 encoded JS
    # CSS injection via style attributes
    r'(?i)style\s*=\s*["\'][^"\']*expression\s*\(',  # style="expression(...)"
    r'(?i)style\s*=\s*["\'][^"\']*url\s*\(\s*["\']?javascript:',  # style="url(javascript:...)"
    # HTML5 new tags/attributes
    r'(?i)<audio\b',  # audio tags
    r'(?i)<video\b',  # video tags
    r'(?i)<source\b',  # source tags
    r'(?i)<track\b',  # track tags
    r'(?i)<canvas\b',  # canvas tags
    # Form-related attacks
    r'(?i)<form\b[^>]*action\s*=\s*["\']?javascript:',  # form action=javascript:...
    r'(?i)<form\b[^>]*action\s*=\s*["\']?data:',  # form action=data:...
    # Meta refresh redirects
    r'(?i)<meta\b[^>]*http-equiv\s*=\s*["\']?refresh',  # meta refresh
    r'(?i)<meta\b[^>]*content\s*=\s*["\']?\d*;\s*url\s*=\s*javascript:',  # meta refresh to javascript:...
    # Object/embed data
    r'(?i)<object\b[^>]*data\s*=\s*["\']?javascript:',  # object data=javascript:...
    r'(?i)<embed\b[^>]*src\s*=\s*["\']?javascript:',  # embed src=javascript:...
    # Picture element
    r'(?i)<picture\b',  # picture tags
    r'(?i)<source\b[^>]*srcset\s*=\s*["\']?javascript:',  # source srcset=javascript:...
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
        # Use constant for special character validation
        special_chars = re.escape(PASSWORD_SPECIAL_CHARS)
        if not re.search(f'[{special_chars}]', v):
            raise ValueError(f'Password must contain at least one special character ({PASSWORD_SPECIAL_CHARS})')
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
