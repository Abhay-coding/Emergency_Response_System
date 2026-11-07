# Campus Medical Assistance

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109+-green.svg)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15+-blue.svg)](https://www.postgresql.org/)
[![Redis](https://img.shields.io/badge/Redis-7+-red.svg)](https://redis.io/)
[![Docker](https://img.shields.io/badge/Docker-Ready-blue.svg)](https://www.docker.com/)
[![AWS ECS](https://img.shields.io/badge/AWS_ECS-Fargate-orange.svg)](https://aws.amazon.com/fargate/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

A FastAPI application for requesting and tracking campus medical assistance, designed for **AWS ECS Fargate + RDS** deployment. The incident model remains in the API; the web interface creates and lists medical requests.

## Medical emergency flow (new)

The home screen now opens a **medical-only** flow. A student can send an alert with one tap, even without signing in. Location, callback number, and details can be added afterward. A bystander can report another student's emergency. Admins claim requests, contact the reporter, notify department or hostel staff, and record medical team dispatch. Staff with accounts can acknowledge and send findings. Caretakers are alerted only after admin review.

The campus place list is seeded from the college locations supplied for this project. Admins configure coverage and day/night staff contacts; the app suggests configured nearby staff and lets an admin override the suggestion. A lack of reply is never treated as proof of a prank.

### Run a local demo

1. Start the app with `Start-Local.cmd` or `python -m uvicorn app.main:app --reload`.
2. In a second terminal, run `python -m app.cli create-admin admin@your-college.edu` and enter an admin password.
3. The one-click launcher starts the local notification worker as well. If you start Uvicorn manually, run `python -m app.worker` in another terminal. With `NOTIFICATION_MODE=simulation`, jobs are marked **simulated**, never delivered.
4. Sign in as admin, add staff contacts and optional staff logins, and configure coverage for each place in the admin portal.
5. Set `CAMPUS_EMERGENCY_PHONE` and `BACKUP_PHONE` only to verified college numbers. The admin portal shows missing setup and failed jobs.

The browser app is a project prototype until the college supplies a staffed duty roster, verifies all contact numbers, configures an approved outbound provider, and tests delivery and escalation. It does not claim that a simulated alert reached anyone.

### Cloud computing architecture

See [docs/CLOUD-ARCHITECTURE.md](docs/CLOUD-ARCHITECTURE.md) for the ECS, RDS, SQS, SNS, worker, migration, and monitoring path. The API and worker use the same container image with different commands. Run `alembic upgrade head` as a one-off deployment task before starting production services. Local SQLite startup creates tables for development; production startup requires the migrated schema.

---

## 🎯 Features

### Core Functionality
- **Authentication & Authorization**: JWT-based access/refresh tokens with rotation, theft detection, and family-based revocation
- **Role-Based Access Control**: Three roles — Reporter, Responder, Admin — with granular permissions
- **Medical Requests**: Report a medical situation with an optional image, then track assignment and status
- **Analytics Dashboard**: Real-time incident summaries with SQL-optimized aggregations

### Security First
- **Token Security**: Family-based refresh token rotation with automatic theft detection
- **Input Validation**: Multi-layer XSS protection (40+ regex patterns), magic byte file validation
- **Security Headers**: Strict CSP, HSTS, COOP, CORP, Permissions-Policy, and more
- **Rate Limiting**: User-ID based (authenticated) + IP-based (anonymous) with configurable windows
- **Audit Logging**: Structured security event logging for compliance

### Observability
- **Health Checks**: `/health` (DB + Redis), `/ready` (K8s/ECS readiness), `/live` (liveness)
- **Metrics**: Prometheus `/metrics` endpoint with custom business metrics
- **Structured Logging**: JSON/text output via `structlog` with request tracing
- **Request Tracing**: Unique `X-Request-ID` on every response

### Infrastructure Ready
- **Database**: PostgreSQL (RDS) with connection pooling, SQLite (dev) — auto-detected
- **Caching**: Redis-backed token blacklist with in-memory fallback
- **Container**: Multi-stage Docker build (non-root, minimal attack surface)
- **Orchestration**: ECS Fargate task/service definitions, EFS for persistent uploads
- **Migrations**: Alembic with auto-generation support

---

## 🚀 Quick Start

Open the web app at `http://127.0.0.1:8000/` after starting the server. Opening `frontend/index.html` directly shows the interface, but requests and sign-in need the running API.

### Windows: start with one click

Double-click `Start-Local.cmd`. It creates the local Python environment when needed, installs the Python packages on first run, starts the API and frontend together, then opens the app at `http://127.0.0.1:8000/`. If port 8000 is already in use, it selects the next available port automatically. Keep the PowerShell window open while you use the app; press `Ctrl+C` there to stop it.

`Start-Local.ps1` contains the launcher itself. You can also right-click it and choose **Run with PowerShell**.

### Prerequisites
- **Docker** & **Docker Compose** (recommended)
- **Python 3.11+** (for manual development)
- **AWS CLI** + **Docker** (for ECS deployment)

### 1. Development with Docker Compose (Recommended)

```bash
# Clone and navigate
cd emergency-response

# Copy environment template
cp .env.example .env

# Start all services (API, PostgreSQL, Redis, Prometheus, Grafana)
docker-compose up -d

# Verify services
docker-compose ps

# API:        http://localhost:8000
# Docs:       http://localhost:8000/docs
# Grafana:    http://localhost:3000 (admin/admin)
# Prometheus: http://localhost:9090
```

### 2. Manual Development Setup

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your settings (JWT_SECRET is REQUIRED)

# Generate secure JWT secret
# Linux/macOS: openssl rand -hex 32
# Python: python -c "import secrets; print(secrets.token_hex(32))"

# Run migrations
alembic upgrade head

# Start development server with auto-reload
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 3. Run Tests

```bash
# Unit tests with coverage
pytest -v --cov=app --cov-report=term-missing

# HTML coverage report
pytest --cov=app --cov-report=html

# Security-focused tests
python test_security_fixes.py
```

---

## 📚 API Reference

### Authentication Endpoints
| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| `POST` | `/api/v1/auth/register` | Register new Reporter | ❌ |
| `POST` | `/api/v1/auth/login` | Login, get tokens | ❌ |
| `POST` | `/api/v1/auth/refresh` | Rotate access token | ❌ |
| `POST` | `/api/v1/auth/logout` | Revoke current session | ✅ |
| `POST` | `/api/v1/auth/logout/all` | Revoke all sessions | ✅ |
| `GET` | `/api/v1/auth/me` | Current user profile | ✅ |

### Incident Endpoints
| Method | Endpoint | Description | Roles |
|--------|----------|-------------|-------|
| `POST` | `/api/v1/incidents/` | Create incident | Reporter+ |
| `GET` | `/api/v1/incidents/` | List incidents (paginated, filtered) | Reporter+ |
| `GET` | `/api/v1/incidents/{id}` | Get incident details | Reporter+ |
| `POST` | `/api/v1/incidents/{id}/image` | Upload incident image | Reporter+ |
| `GET` | `/api/v1/incidents/{id}/image` | Download incident image | Reporter+ |
| `PATCH` | `/api/v1/incidents/{id}/assign` | Assign to Responder | Admin |
| `PATCH` | `/api/v1/incidents/{id}/status` | Update status | Responder+ |
| `GET` | `/api/v1/incidents/analytics/summary` | Aggregated analytics | Admin |

### System Endpoints
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | API metadata |
| `GET` | `/health` | Full health check (DB + Redis) |
| `GET` | `/ready` | Kubernetes/ECS readiness probe |
| `GET` | `/live` | Kubernetes/ECS liveness probe |
| `GET` | `/metrics` | Prometheus metrics |

---

## ⚙️ Configuration

### Environment Variables

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `ENVIRONMENT` | `development` \| `staging` \| `production` | `development` | No |
| `DATABASE_URL` | SQLAlchemy connection string | `sqlite:///./emergency.db` | No* |
| `JWT_SECRET` | JWT signing key (32+ chars) | — | **Yes** |
| `ACCESS_TOKEN_MINUTES` | Access token TTL | `60` | No |
| `REFRESH_TOKEN_DAYS` | Refresh token TTL | `7` | No |
| `REDIS_URL` | Redis connection (for blacklist/rate limit) | `None` | No |
| `RATE_LIMIT_REQUESTS` | Requests per window | `100` | No |
| `RATE_LIMIT_WINDOW` | Rate limit window (seconds) | `60` | No |
| `CORS_ORIGINS` | JSON array of allowed origins | `["http://localhost:5500"]` | No |
| `LOG_LEVEL` | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` | `INFO` | No |
| `LOG_FORMAT` | `json` \| `text` | `json` | No |
| `MAX_UPLOAD_SIZE_MB` | Max image upload size | `5` | No |

> * `DATABASE_URL` is required for production. SQLite is used as fallback for development.

### Example `.env` Files

**Development (`.env`)**:
```bash
ENVIRONMENT=development
DATABASE_URL=sqlite:///./emergency.db
JWT_SECRET=your-super-secret-jwt-key-min-32-chars
REDIS_URL=redis://localhost:6379/0
CORS_ORIGINS=["http://localhost:3000","http://localhost:5500"]
LOG_LEVEL=DEBUG
LOG_FORMAT=text
```

**Production (`.env.production`)**:
```bash
ENVIRONMENT=production
DATABASE_URL=postgresql+psycopg://user:pass@rds-endpoint:5432/dbname
JWT_SECRET=rotate-this-regularly-in-secrets-manager
ACCESS_TOKEN_MINUTES=30
REFRESH_TOKEN_DAYS=3
REDIS_URL=redis://elasticache-endpoint:6379/0
RATE_LIMIT_REQUESTS=200
RATE_LIMIT_WINDOW=60
CORS_ORIGINS=["https://your-frontend-domain.com"]
LOG_LEVEL=INFO
LOG_FORMAT=json
MAX_UPLOAD_SIZE_MB=10
```

---

## 🗄️ Database Migrations

```bash
# Generate new migration (after model changes)
alembic revision --autogenerate -m "descriptive message"

# Apply all pending migrations
alembic upgrade head

# Rollback one migration
alembic downgrade -1

# Show current migration
alembic current

# Show migration history
alembic history
```

---

## 🐳 Docker & Deployment

### Local Docker Build
```bash
# Build image
docker build -t emergency-response-api .

# Run container
docker run -d \
  -p 8000:8000 \
  --env-file .env \
  -v $(pwd)/uploads:/app/uploads \
  emergency-response-api
```

### AWS ECS Fargate Deployment

#### Prerequisites
- AWS Account with: ECS, ECR, RDS (PostgreSQL), ElastiCache (Redis), ALB, EFS, IAM
- AWS CLI configured with appropriate permissions
- Docker installed and authenticated to ECR

#### 1. Build & Push to ECR
```bash
# Login to ECR
aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin ${ACCOUNT_ID}.dkr.ecr.us-east-1.amazonaws.com

# Build, tag, push
docker build -t emergency-response-api .
docker tag emergency-response-api:latest \
  ${ACCOUNT_ID}.dkr.ecr.us-east-1.amazonaws.com/emergency-response-api:latest
docker push ${ACCOUNT_ID}.dkr.ecr.us-east-1.amazonaws.com/emergency-response-api:latest
```

#### 2. Infrastructure (Terraform/CloudFormation)
Create these resources:
1. **VPC** with public/private subnets across 2+ AZs
2. **RDS PostgreSQL 15+** in private subnets (Multi-AZ for production)
3. **ElastiCache Redis 7+** in private subnets
4. **EFS** for persistent `/app/uploads` with access points
5. **Application Load Balancer** with HTTPS listener + target group
6. **ECS Cluster** (Fargate, capacity provider: FARGATE)
7. **IAM Roles**: Task Execution Role, Task Role (with Secrets Manager access)
8. **CloudWatch Log Group** for container logs

#### 3. Deploy ECS Resources
```bash
# Register task definition (update image URI, secrets ARNs first)
aws ecs register-task-definition --cli-input-json file://ecs-task-definition.json

# Create or update service
aws ecs create-service --cli-input-json file://ecs-service.json
# Or update existing:
aws ecs update-service --cluster emergency-response-cluster \
  --service emergency-response-api \
  --task-definition emergency-response-api:latest \
  --force-new-deployment
```

#### 4. Secrets Manager
Store in AWS Secrets Manager:
- `emergency-response/jwt-secret` — JWT signing key
- `emergency-response/database-url` — Full PostgreSQL connection string
- `emergency-response/redis-url` — ElastiCache endpoint (optional)

---

## 📁 Project Structure

```
emergency-response/
├── app/
│   ├── core/
│   │   ├── config.py              # Pydantic settings (env-based)
│   │   ├── security.py            # JWT, Argon2 password hashing
│   │   ├── token_blacklist.py     # Redis-backed + DB persistence
│   │   ├── rate_limit.py          # User-ID based rate limiting
│   │   └── audit.py               # Structured security logging
│   ├── routers/
│   │   ├── auth.py                # Auth endpoints (register/login/refresh/logout)
│   │   └── incidents.py           # Incident CRUD + image upload
│   ├── models.py                  # SQLAlchemy models (User, Incident, TokenFamily)
│   ├── schemas.py                 # Pydantic schemas + XSS validation
│   ├── dependencies.py            # FastAPI deps (auth, rate limit keys)
│   ├── database.py                # SQLAlchemy engine + session (PG + SQLite)
│   └── main.py                    # FastAPI app + middleware + health checks
├── migrations/
│   ├── env.py                     # Alembic environment
│   └── versions/                  # Auto-generated migrations
├── tests/                         # (Add your tests here)
├── Dockerfile                     # Multi-stage production build
├── docker-compose.yml             # Local dev stack
├── ecs-task-definition.json       # ECS Fargate task definition
├── ecs-service.json               # ECS service definition
├── prometheus.yml                 # Prometheus scrape config
├── requirements.txt               # Python dependencies
├── alembic.ini                   # Alembic configuration
├── test_security_fixes.py         # Security regression tests
├── .env.example                   # Environment template
├── .gitignore                     # Comprehensive ignore patterns
├── LICENSE                        # MIT License
└── README.md                      # This file
```

---

## 🔒 Security Architecture

### Token Management
```
Login → Creates TokenFamily (DB + Redis)
       ↓
Access Token (60 min) + Refresh Token (7 days, family_id)
       ↓
Refresh Request → Validates family + JTI → Rotates token
       ↓
Theft Detection → Reused JTI? → Revoke entire family
       ↓
Logout → Blacklist access JTI + Revoke user's families
```

### File Upload Security
1. **Extension validation** — allowlist only (`.jpg`, `.jpeg`, `.png`, `.webp`)
2. **Magic byte detection** — verifies actual file format (JPEG/PNG/WEBP signatures)
3. **MIME type verification** — python-magic library (with graceful fallback)
4. **Size limit** — configurable (default 5MB)
5. **Path traversal protection** — resolved path must be within upload directory
6. **Secure storage** — UUID filenames, no user-controlled paths

### Rate Limiting Strategy
| Context | Key | Default Limit |
|---------|-----|---------------|
| Authenticated | `user:{user_id}` | 100 req/min |
| Anonymous | `ip:{client_ip}` | 100 req/min |
| Auth endpoints | Stricter limits | 5-20 req/min |

---

## 📊 Monitoring & Observability

### Health Checks
```bash
# Full health (load balancer target)
curl http://localhost:8000/health
# {"status": "healthy", "checks": {"database": "ok", "redis": "ok"}}

# Readiness (K8s/ECS)
curl http://localhost:8000/ready

# Liveness (K8s/ECS)
curl http://localhost:8000/live
```

### Prometheus Metrics
```bash
curl http://localhost:8000/metrics
```
Exposes: HTTP request duration, DB query latency, token operations, business metrics.

### Structured Logs
```json
{
  "timestamp": "2026-11-03T12:00:00.000Z",
  "level": "INFO",
  "request_id": "abc-123",
  "method": "POST",
  "path": "/api/v1/auth/login",
  "status_code": 200,
  "duration_ms": 45.2
}
```

---

## 🧪 Testing

```bash
# Run all tests
pytest -v --cov=app

# Security regression tests
python test_security_fixes.py

# Load testing (example)
locust -f tests/load_test.py --host=http://localhost:8000
```

### Test Coverage Targets
- **Unit tests**: ≥ 80% coverage
- **Security tests**: 100% critical path coverage
- **Integration tests**: All API endpoints

---

## 🤝 Contributing

1. Fork the repository
2. Create feature branch: `git checkout -b feature/amazing-feature`
3. Run tests: `pytest --cov=app`
4. Run security tests: `python test_security_fixes.py`
5. Format code: `black . && isort . && ruff check .`
6. Commit: `git commit -m "feat: add amazing feature"`
7. Push: `git push origin feature/amazing-feature`
8. Open Pull Request

---

## 📝 License

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

- **FastAPI** — Modern, fast web framework
- **SQLAlchemy** — Python SQL toolkit and ORM
- **Pydantic** — Data validation using Python type hints
- **Redis** — In-memory data structure store
- **PostgreSQL** — Advanced open-source relational database
- **Alembic** — Database migration tool for SQLAlchemy
- **structlog** — Structured logging for Python

---

## 📞 Support

- **Issues**: [GitHub Issues](https://github.com/your-org/emergency-response/issues)
- **Security**: Report vulnerabilities to security@your-org.com
- **Documentation**: See `/docs` endpoint when running locally

---

*Built with ❤️ for campus safety and emergency response teams.*
