from pathlib import Path
from uuid import uuid4
from io import BytesIO

from fastapi import HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError

from app.core.config import settings


ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}


def save_upload(file: UploadFile) -> str:
    raw = file.file.read(settings.max_upload_size_mb * 1024 * 1024 + 1)

    if len(raw) > settings.max_upload_size_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Image exceeds size limit")

    try:
        image = Image.open(BytesIO(raw))
        image.verify()
        if image.format not in ALLOWED_FORMATS:
            raise HTTPException(status_code=415, detail="Use JPEG, PNG or WEBP")
    except (UnidentifiedImageError, OSError):
        raise HTTPException(status_code=415, detail="Invalid image file")

    directory = Path(settings.upload_dir)
    directory.mkdir(parents=True, exist_ok=True)

    extension = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}[image.format]
    filename = f"{uuid4().hex}{extension}"
    destination = directory / filename
    destination.write_bytes(raw)
    return str(destination)
