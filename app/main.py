from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.database import Base, engine
from app import models
from app.routers import auth, incidents

Base.metadata.create_all(bind=engine)

Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title=settings.app_name,
    description="Campus incident reporting and response API",
    version="0.1.0",
)

from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5500",
        "http://localhost:5500",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(incidents.router)

app.mount(
    "/uploads",
    StaticFiles(directory=settings.upload_dir),
    name="uploads",
)


@app.get("/", tags=["System"])
def home():
    return {
        "message": settings.app_name,
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health", tags=["System"])
def health():
    return {"status": "ok"}
