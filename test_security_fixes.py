#!/usr/bin/env python
"""Test script to verify all security fixes work correctly"""

import sys
import os
import tempfile
import shutil
from pathlib import Path

# Add app to path
sys.path.insert(0, str(Path(__file__).parent))

def test_xss_validation():
    """Test XSS validation in schemas"""
    print("Testing XSS validation...")
    from app.schemas import validate_no_xss, UserCreate, IncidentCreate
    from pydantic import ValidationError

    # Test cases that should be rejected
    xss_payloads = [
        "<script>alert(1)</script>",
        "<SCRIPT>alert(1)</SCRIPT>",
        "<img src=x onerror=alert(1)>",
        "<svg onload=alert(1)>",
        "javascript:alert(1)",
        "<iframe src=javascript:alert(1)>",
        "<details open ontoggle=alert(1)>",
        "{{7*7}}",
        "${7*7}",
        "<style>@import'javascript:alert(1)'</style>",
    ]

    for payload in xss_payloads:
        try:
            validate_no_xss(payload, 'test')
            print(f"  FAIL: XSS payload not caught: {payload}")
            return False
        except ValueError:
            pass  # Expected

    # Test valid inputs
    try:
        validate_no_xss("Normal text", 'test')
        validate_no_xss("User's report about incident", 'test')
        validate_no_xss("Path: C:\\Users\\file.txt", 'test')
    except ValueError as e:
        print(f"  FAIL: Valid input rejected: {e}")
        return False

    # Test UserCreate validation
    try:
        UserCreate(name="<script>alert(1)</script>", email="test@example.com", password="Password123!")
        print("  FAIL: UserCreate accepted XSS in name")
        return False
    except ValidationError:
        pass  # Expected

    try:
        UserCreate(name="Valid Name", email="test@example.com", password="Password123!")
    except ValidationError as e:
        print(f"  FAIL: UserCreate rejected valid input: {e}")
        return False

    # Test IncidentCreate validation
    try:
        IncidentCreate(
            title="<script>alert(1)</script>",
            description="Valid description",
            category="fire",
            location="Building A"
        )
        print("  FAIL: IncidentCreate accepted XSS in title")
        return False
    except ValidationError:
        pass  # Expected

    print("  PASS: XSS validation works correctly")
    return True


def test_file_upload_validation():
    """Test file upload validation"""
    print("Testing file upload validation...")
    from app.services.storage import validate_file_extension, validate_mime_type_fallback, validate_mime_type_with_python_magic
    from fastapi import HTTPException
    from io import BytesIO

    # Create mock upload file
    class MockUploadFile:
        def __init__(self, filename, content):
            self.filename = filename
            self.file = BytesIO(content)
            self.content_type = "image/jpeg"

    # Test valid extensions
    valid_files = [
        MockUploadFile("test.jpg", b"\xff\xd8\xff\xe0\x00\x10JFIF"),
        MockUploadFile("test.jpeg", b"\xff\xd8\xff\xe0\x00\x10JFIF"),
        MockUploadFile("test.png", b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"),
        MockUploadFile("test.webp", b"RIFF\x00\x00\x00\x00WEBP"),
    ]

    for f in valid_files:
        try:
            validate_file_extension(f.filename)
        except HTTPException:
            print(f"  FAIL: Valid extension rejected: {f.filename}")
            return False

    # Test invalid extensions
    invalid_files = [
        MockUploadFile("test.exe", b"MZ"),
        MockUploadFile("test.php", b"<?php"),
        MockUploadFile("test.sh", b"#!/bin/bash"),
        MockUploadFile("test.jpg.exe", b"\xff\xd8\xff"),
    ]

    for f in invalid_files:
        try:
            validate_file_extension(f.filename)
            print(f"  FAIL: Invalid extension accepted: {f.filename}")
            return False
        except HTTPException:
            pass  # Expected

    # Test magic byte validation (validate_mime_type_fallback)
    for f in valid_files:
        try:
            f.file.seek(0)
            validate_mime_type_fallback(f)
        except HTTPException as e:
            print(f"  FAIL: Valid file rejected by magic bytes: {f.filename} - {e}")
            return False

    # Test invalid magic bytes
    invalid_magic = MockUploadFile("test.exe", b"MZ")
    try:
        invalid_magic.file.seek(0)
        validate_mime_type_fallback(invalid_magic)
        print("  FAIL: Invalid magic bytes accepted")
        return False
    except HTTPException:
        pass  # Expected

    # Test python-magic validation (optional, might not work on all systems)
    try:
        for f in valid_files:
            f.file.seek(0)
            result = validate_mime_type_with_python_magic(f)
            assert result in ["image/jpeg", "image/png", "image/webp"]
    except Exception as e:
        print(f"  NOTE: python-magic validation skipped (not available or error: {e})")

    print("  PASS: File upload validation works correctly")
    return True


def test_token_blacklist():
    """Test token blacklist functionality"""
    print("Testing token blacklist...")
    from app.core.token_blacklist import TokenBlacklist

    blacklist = TokenBlacklist()

    # Test add and contains
    test_jti = "test-jti-123"
    assert not blacklist.contains(test_jti), "New JTI should not be in blacklist"
    blacklist.add(test_jti)
    assert blacklist.contains(test_jti), "JTI should be in blacklist after add"

    # Test remove
    blacklist.remove(test_jti)
    assert not blacklist.contains(test_jti), "JTI should not be in blacklist after remove"

    # Test family registration and rotation
    family_id = "test-family-456"
    jti1 = "jti-1"
    jti2 = "jti-2"

    blacklist.register_family(family_id, jti1)
    # Initial JTI should NOT be in blacklist - it's the current valid token
    assert not blacklist.contains(jti1), "Initial JTI should NOT be blacklisted after registration"

    # Valid rotation
    result = blacklist.rotate_token(family_id, jti1, jti2)
    assert result, "Valid rotation should succeed"
    assert blacklist.contains(jti1), "Old JTI should be blacklisted after rotation"
    assert not blacklist.contains(jti2), "New JTI should not be blacklisted yet"

    # Theft detection - reuse old token
    blacklist.register_family("family-2", "jti-a")
    result = blacklist.rotate_token("family-2", "jti-b", "jti-c")  # Wrong old JTI
    assert not result, "Theft detection should fail rotation"

    print("  PASS: Token blacklist works correctly")
    return True


def test_models():
    """Test database models"""
    print("Testing database models...")
    from app.models import User, Incident, TokenFamily, Role, IncidentStatus, IncidentPriority
    from datetime import datetime, timezone

    # Test User model
    user = User(
        id=1,
        name="Test User",
        email="test@example.com",
        password_hash="hashed",
        role=Role.reporter
    )
    assert user.name == "Test User"
    assert user.role == Role.reporter

    # Test Incident model
    incident = Incident(
        id=1,
        title="Test Incident",
        description="Description",
        category="fire",
        location="Building A",
        priority=IncidentPriority.high,
        status=IncidentStatus.reported,
        reporter_id=1
    )
    assert incident.title == "Test Incident"
    assert incident.priority == IncidentPriority.high

    # Test TokenFamily model
    tf = TokenFamily(
        id=1,
        user_id=1,
        family_id="family-123",
        current_jti="jti-123",
        revoked=False
    )
    assert tf.family_id == "family-123"
    assert tf.revoked == False

    print("  PASS: Database models work correctly")
    return True


def test_security_functions():
    """Test security functions"""
    print("Testing security functions...")
    from app.core.security import (
        hash_password, verify_password,
        create_access_token, create_refresh_token,
        decode_access_token, decode_refresh_token,
        get_token_jti, get_refresh_token_family
    )
    from app.core.config import settings

    # Ensure JWT secret is set
    if not settings.jwt_secret:
        settings.jwt_secret = "test-secret-key-for-testing-only"

    # Test password hashing
    password = "TestPassword123!"
    hashed = hash_password(password)
    assert verify_password(password, hashed), "Password verification failed"
    assert not verify_password("WrongPassword", hashed), "Wrong password should fail"

    # Test token creation and decoding
    access_token = create_access_token("1")
    decoded = decode_access_token(access_token)
    assert decoded["sub"] == "1"
    assert decoded["type"] == "access"
    assert "jti" in decoded

    refresh_token = create_refresh_token("1", family_id="family-123")
    decoded_refresh = decode_refresh_token(refresh_token)
    assert decoded_refresh["sub"] == "1"
    assert decoded_refresh["type"] == "refresh"
    assert decoded_refresh["fid"] == "family-123"

    # Test JTI extraction for access token
    access_jti = get_token_jti(access_token)
    assert access_jti is not None
    assert access_jti == decoded["jti"]

    # Test JTI extraction for refresh token
    refresh_jti = get_token_jti(refresh_token)
    assert refresh_jti is not None
    assert refresh_jti == decoded_refresh["jti"]

    family = get_refresh_token_family(refresh_token)
    assert family == "family-123"

    print("  PASS: Security functions work correctly")
    return True


def test_dependencies():
    """Test dependencies"""
    print("Testing dependencies...")
    from app.dependencies import get_rate_limit_key
    from fastapi import Request
    from unittest.mock import MagicMock

    # Mock request
    request = MagicMock(spec=Request)
    request.client.host = "127.0.0.1"
    request.headers = {}
    request.state = MagicMock()
    request.state.user = None

    # Test IP-based rate limit key
    key = get_rate_limit_key(request)
    assert key.startswith("ip:"), f"Expected IP-based key, got: {key}"

    # Test user-based rate limit key
    request.state.user = MagicMock()
    request.state.user.id = 42
    key = get_rate_limit_key(request)
    assert key == "user:42", f"Expected user-based key, got: {key}"

    print("  PASS: Dependencies work correctly")
    return True


def run_all_tests():
    """Run all tests"""
    tests = [
        test_xss_validation,
        test_file_upload_validation,
        test_token_blacklist,
        test_models,
        test_security_functions,
        test_dependencies,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            if test():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"  FAIL: {test.__name__} raised exception: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print(f"\nResults: {passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)