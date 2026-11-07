from pathlib import Path
from uuid import uuid4
import tempfile
import os

from fastapi import HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError

from app.core.config import settings
from app.core.constants import (
    ALLOWED_IMAGE_FORMATS,
    ALLOWED_IMAGE_EXTENSIONS,
    ALLOWED_MIME_TYPES,
    IMAGE_MAGIC_BYTES,
    UPLOAD_CHUNK_SIZE_BYTES,
)


def validate_file_extension(filename: str) -> None:
    """Validate file extension against allowed extensions"""
    if not filename:
        raise HTTPException(status_code=415, detail="Filename is required")
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"File extension '{ext}' not allowed. Allowed: {', '.join(ALLOWED_IMAGE_EXTENSIONS)}"
        )


def validate_mime_type_with_python_magic(file: UploadFile) -> str:
    """Validate MIME type using python-magic library"""
    try:
        import magic
    except ImportError:
        raise HTTPException(status_code=500, detail="python-magic not available")

    chunk = file.file.read(8192)
    file.file.seek(0)

    if not chunk:
        raise HTTPException(status_code=415, detail="Empty file")

    try:
        mime_type = magic.from_buffer(chunk, mime=True)
    except Exception as e:
        raise HTTPException(status_code=415, detail=f"MIME type detection failed: {e}")

    if mime_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"MIME type '{mime_type}' not allowed. Allowed: {', '.join(ALLOWED_MIME_TYPES)}"
        )

    return mime_type


def validate_mime_type_fallback(file: UploadFile) -> None:
    """Fallback MIME type validation using magic bytes"""
    header = file.file.read(12)
    file.file.seek(0)

    if not header:
        raise HTTPException(status_code=415, detail="Empty file")

    detected_format = None
    for magic_bytes, fmt in IMAGE_MAGIC_BYTES.items():
        if header.startswith(magic_bytes):
            if fmt == 'WEBP':
                more = file.file.read(20)
                file.file.seek(0)
                if b'WEBP' in header + more:
                    detected_format = 'WEBP'
            else:
                detected_format = fmt
            break

    if not detected_format:
        raise HTTPException(status_code=415, detail="Invalid image format. Only JPEG, PNG, and WEBP are allowed.")

    if detected_format not in ALLOWED_IMAGE_FORMATS:
        raise HTTPException(status_code=415, detail="Image format not allowed")


def save_upload(file: UploadFile, prefix: str = "") -> str:
    """Save upload with streaming validation - writes to temp file first"""
    max_size = settings.max_upload_size_mb * 1024 * 1024

    # Validate file extension first
    validate_file_extension(file.filename)

    # Validate MIME type from content
    try:
        validate_mime_type_with_python_magic(file)
    except ImportError:
        validate_mime_type_fallback(file)

    # Create temp file for streaming write
    temp_fd, temp_path = tempfile.mkstemp(dir=settings.upload_dir, suffix=".tmp")
    os.close(temp_fd)

    try:
        # Stream write to temp file with size limit
        total_size = 0
        with open(temp_path, "wb") as f:
            while True:
                chunk = file.file.read(UPLOAD_CHUNK_SIZE_BYTES)
                if not chunk:
                    break
                total_size += len(chunk)
                if total_size > max_size:
                    raise HTTPException(status_code=413, detail="Image exceeds size limit")
                f.write(chunk)

        # Validate the image after writing using PIL
        try:
            image = Image.open(temp_path)
            image.verify()
            if image.format not in ALLOWED_IMAGE_FORMATS:
                raise HTTPException(status_code=415, detail="Use JPEG, PNG or WEBP")
        except (UnidentifiedImageError, OSError):
            raise HTTPException(status_code=415, detail="Invalid image file")

        # Re-open to get format (verify() closes the image)
        image = Image.open(temp_path)
        image_format = image.format
        image.close()

        # Move temp file to final location
        directory = Path(settings.upload_dir)
        directory.mkdir(parents=True, exist_ok=True)

        extension = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}[image_format]
        filename = f"{prefix}{uuid4().hex}{extension}" if prefix else f"{uuid4().hex}{extension}"
        destination = directory / filename

        os.replace(temp_path, destination)
        return str(destination)

    except HTTPException:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise
    except Exception:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise HTTPException(status_code=500, detail="Failed to save image")
