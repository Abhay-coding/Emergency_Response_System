"""AWS Lambda entry point for the FastAPI application."""

from mangum import Mangum

from app.main import app


handler = Mangum(app, lifespan="auto")
