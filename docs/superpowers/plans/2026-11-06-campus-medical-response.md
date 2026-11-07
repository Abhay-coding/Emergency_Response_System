# Campus Medical Response Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a medical-only, one-tap campus alert system with guest access, human admin triage, nearby staff handoff, cloud-ready escalation, and an accessible student/staff/admin interface.

**Architecture:** Keep the legacy incident API compatible and add a dedicated medical alert workflow. Persist all state in SQLAlchemy, use an outbox/worker for reliable notification delivery, and integrate an optional AWS managed queue and outbound provider for cloud deployment. Serve a redesigned plain HTML/CSS/JavaScript frontend from FastAPI.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, PostgreSQL/SQLite, vanilla JavaScript, CSS, Docker, AWS ECS/RDS/CloudWatch with SQS and SNS integration where configured.

**Spec:** `docs/superpowers/specs/2026-11-06-campus-medical-response-design.md`

## Global Constraints

- All user-facing workflows are for medical emergencies or suspected medical incidents only.
- One tap submits before optional location, identity, callback, or symptom details.
- Guest access uses an unguessable expiring token; no public numeric-ID lookup.
- No response must never become an automatic false report.
- Caretakers are notified only after admin action.
- Unconfigured or failed outbound notification is shown truthfully.
- Preserve existing uncommitted user changes and legacy incident data.
- Follow the UI/UX Pro Max accessible and ethical direction: high contrast, 44px touch targets, visible focus, responsive layout, reduced motion.

## Review Focus

- Denied geolocation and absent campus place still create an alert.
- Duplicate tap or retry does not create multiple alerts.
- Guest token leakage, expiry, and cross-alert access.
- Two admins claiming the same alert at once.
- Worker restart or duplicate queue message does not duplicate backup escalation.

## Task 1: Durable medical alert and guest submission

**Files:** `app/models.py`, `app/schemas.py`, `app/routers/medical_alerts.py`, `app/main.py`, Alembic migration, `tests/test_medical_alerts.py`.

- [ ] Add alert, event, message, and token data with a versioned migration that preserves existing rows.
- [ ] Add one-tap endpoint for guest or authenticated reporter with idempotency and no required fields.
- [ ] Add token-protected status and optional follow-up location/contact updates.
- [ ] Test authenticated/guest creation, duplicate retry, token isolation, and missing location.

## Task 2: Admin, staff, and campus directory

**Files:** `app/models.py`, `app/schemas.py`, `app/routers/medical_alerts.py`, `app/routers/campus.py`, migrations, `tests/test_medical_workflow.py`.

- [ ] Seed editable campus place names from the approved list and allow admins to configure coverage, staff contacts, and shifts.
- [ ] Add admin queue, atomic claim, contact attempt, verification, staff alert, medical dispatch, false-report reason, and event history.
- [ ] Add staff inbox, acknowledgement, and findings. Restrict each staff account to assigned alerts.
- [ ] Test role permissions, hostel post-review notification, status transitions, and audit history.

## Task 3: Cloud-ready notification and escalation

**Files:** `app/services/notifications.py`, `app/worker.py`, `app/core/config.py`, ECS worker config, deployment docs, `tests/test_notifications.py`.

- [ ] Persist outbound jobs and a 60-second backup deadline; process them independently of API process lifetime.
- [ ] Support local simulation marked as such and optional AWS SQS/SNS delivery with send/failed/acknowledged states.
- [ ] Retry transient failure, prevent duplicate sends, and expose failed jobs and coverage health in admin UI/API.
- [ ] Test no-admin timeout, late acknowledgement, provider failure, and worker restart semantics.

## Task 4: Medical-only frontend redesign

**Files:** `frontend/index.html`, `frontend/style.css`, `frontend/app.js`, frontend support modules if useful.

- [ ] Build a student landing screen where one emergency action dominates; allow guest use and bystander mode.
- [ ] Show truthful request progress, optional place/location/contact details, and direct campus emergency call action.
- [ ] Build admin triage queue and staff inbox with action history, staffing directory, shifts, and notification health.
- [ ] Check responsive sizes, touch targets, keyboard focus, screen reader labels, loading/error states, and reduced motion.

## Task 5: Integration, deployment, and verification

**Files:** `README.md`, deployment artifacts, tests, optional diagram.

- [ ] Run migrations on a copy of the existing database and verify old records survive.
- [ ] Run focused API tests, full test suite, static checks, and browser flows for guest, admin, and staff.
- [ ] Document local demo, cloud architecture, ECS worker, required secrets/contacts, and live-use readiness limits.
- [ ] Correct any issues found by tests or browser checks before reporting completion.
