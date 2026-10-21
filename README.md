# Campus Emergency Response & Resource Management System

A cloud-ready campus incident reporting prototype.

## Current features

- Reporter registration and JWT login
- Role-aware API access
- Incident creation and listing
- Incident image upload with file-type and size checks
- Administrator assignment endpoint
- Responder status updates
- Incident analytics endpoint
- Local SQLite database
- FastAPI interactive documentation

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

Before using this beyond local development, replace `JWT_SECRET` in `.env` with a long random secret. Never commit `.env`.

Run from the project root:

```powershell
python -m uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000/docs

Run tests:

```powershell
python -m pytest
```

## Initial API workflow

1. Register a reporter using `POST /auth/register`.
2. Use `POST /auth/login` with form fields `username` (your email) and `password`.
3. Click Authorize in `/docs` and enter the returned token.
4. Create and list incidents.
5. Upload an image to an incident.
6. Add an administrator and responder through a secure development-only setup process before testing assignment.

Public registration intentionally creates reporter accounts only. Do not grant admin permissions through public registration.

## Cloud integration roadmap

- EC2: host the FastAPI service
- S3: incident-image object storage
- SQS: background work queue
- DynamoDB: cloud incident records
- IAM: least-privilege permissions
- Add production migrations, monitoring, and deployment hardening before public use

This prototype is for coursework and is not yet suitable for real emergency dispatch or production use.
