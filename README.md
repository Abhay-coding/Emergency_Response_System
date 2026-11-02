# Campus Emergency Response & Resource Management System

A secure, cloud-ready campus incident reporting prototype with production-grade security practices.

## Current features

- **Secure Authentication**: JWT access + refresh tokens with Argon2 password hashing
- **Rate Limiting**: Per-endpoint limits (login: 10/min, register: 5/min, etc.)
- **Role-based Access Control**: Reporter, Responder, Admin roles with proper authorization
- **Incident Management**: Create, list (paginated), get, assign, update status
- **Secure Image Upload**: File-type validation (JPEG/PNG/WEBP), size limits, authenticated access
- **Analytics**: Optimized SQL-based aggregation (no full-table scans)
- **Security Headers**: HSTS, CSP, X-Frame-Options, Referrer-Policy
- **Structured Logging**: JSON logs with request IDs for tracing
- **Prometheus Metrics**: `/metrics` endpoint for monitoring
- **API Versioning**: All endpoints under `/api/v1/`
- **Local SQLite Database** (dev) / PostgreSQL ready (prod)

## Security Features Implemented

- ✅ No hardcoded secrets - JWT_SECRET required via environment variable
- ✅ Rate limiting on all auth endpoints
- ✅ Constant-time password verification (prevents email enumeration)
- ✅ Password strength requirements (uppercase, lowercase, digit, special char)
- ✅ No public static file serving - images require authentication
- ✅ Security headers (HSTS, CSP, etc.)
- ✅ CORS restricted to specific origins/methods/headers
- ✅ Request ID tracing for all requests
- ✅ Refresh token rotation
- ✅ Input validation on all endpoints

## Requirements

Python 3.11 or newer is recommended.

## Windows setup

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

**Required**: Edit `.env` and set `JWT_SECRET` with a strong random value:
```powershell
# Generate a secure secret:
openssl rand -base64 64
# Or in Python:
# python -c "import secrets; print(secrets.token_urlsafe(64))"
```

Never commit `.env` to version control.

Run from the project root:

```powershell
python -m uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000/docs

Run tests:

```powershell
python -m pytest
```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `JWT_SECRET` | **YES** | - | 64+ char random string for JWT signing |
| `DATABASE_URL` | No | `sqlite:///./emergency.db` | Database connection string |
| `ACCESS_TOKEN_MINUTES` | No | `60` | Access token expiry |
| `REFRESH_TOKEN_DAYS` | No | `7` | Refresh token expiry |
| `RATE_LIMIT_REQUESTS` | No | `100` | Default rate limit |
| `RATE_LIMIT_WINDOW` | No | `60` | Rate limit window (seconds) |
| `MAX_UPLOAD_SIZE_MB` | No | `5` | Max image upload size |

## API Endpoints (all under `/api/v1/`)

### Authentication
- `POST /api/v1/auth/register` - Register new reporter
- `POST /api/v1/auth/login` - Login (returns access + refresh tokens)
- `POST /api/v1/auth/refresh` - Refresh access token
- `GET /api/v1/auth/me` - Get current user profile

### Incidents
- `POST /api/v1/incidents/` - Create incident
- `GET /api/v1/incidents/` - List incidents (paginated, filterable)
- `GET /api/v1/incidents/{id}` - Get incident details
- `POST /api/v1/incidents/{id}/image` - Upload incident image
- `GET /api/v1/incidents/{id}/image` - Get incident image (authenticated)
- `PATCH /api/v1/incidents/{id}/assign` - Assign to responder (admin only)
- `PATCH /api/v1/incidents/{id}/status` - Update status (responder/admin)
- `GET /api/v1/incidents/analytics/summary` - Analytics (admin only)

### System
- `GET /health` - Health check
- `GET /metrics` - Prometheus metrics

## Initial API workflow

1. Register a reporter using `POST /api/v1/auth/register`.
2. Use `POST /api/v1/auth/login` with form fields `username` (your email) and `password`.
3. Click Authorize in `/docs` and enter the **access_token**.
4. Create and list incidents via `/api/v1/incidents/`.
5. Upload an image to an incident.
6. Add an administrator and responder through a secure development-only setup process before testing assignment.

Public registration intentionally creates reporter accounts only. Do not grant admin permissions through public registration.

## Cloud integration roadmap

- ECS Fargate: host the FastAPI service
- RDS PostgreSQL: production database
- S3: incident-image object storage
- SQS: background work queue
- IAM: least-privilege permissions
- ACM: TLS certificates
- CloudWatch: logging and monitoring
- Add production migrations, monitoring, and deployment hardening before public use

This prototype is for coursework and is not yet suitable for real emergency dispatch or production use without further hardening.
