# Implementation Plan: Complete Campus Medical Alert Workflow

## Goal

Make every visible action in the student, admin, and staff portals complete a real, tested workflow in the deployed GitHub Pages + API Gateway + Lambda + DynamoDB demo. The system remains medical-emergency-only and keeps a human admin as the verifier before staff are alerted.

## Current Reality

The deployed minimum path works: guest alert creation, duplicate-click protection, admin login, queue listing, claim, verify, simulated staff notification, and resolve/false-report closure through the API.

However, the frontend was inherited from the fuller SQLAlchemy application while the deployed Lambda uses the smaller DynamoDB demo router. Several visible controls therefore lead to missing endpoints or incompatible request data.

## Confirmed Dead Ends To Remove

| User action | Current issue | Required outcome |
|---|---|---|
| Student saves place/details/callback | `PATCH /medical-alerts/{id}/location` is absent | Details persist and appear in admin queue |
| Student uses location sharing | Location update route is absent | Either store it or hide/disable the feature clearly |
| Student creates an account | `/auth/register` is absent | Either implement student registration or remove it from this demo |
| Admin adds/edits contacts | Contact write endpoints are absent | Admin can manage the staff directory |
| Admin configures coverage | Coverage endpoints are absent | Suggested nearby/on-duty contacts work |
| Admin sends a message | Messaging endpoints are absent | Hide it for demo, or implement a short message log |
| Admin closes a false report | UI sends `reason`; API expects `note` | Closure succeeds with a clear reason |
| Staff signs in/uses inbox | No deployed staff account/inbox endpoints | Staff can acknowledge and submit findings, or this UI is removed |
| Admin clicks a staff phone link | Seed contacts have no phone numbers | Show configured call links only; never imply delivery |

## Architecture Decisions

- Keep the deployed low-cost stack: GitHub Pages → API Gateway → Lambda → DynamoDB.
- Keep one repository implementation for the deployed demo: `DynamoDemoRepository`. Do not add Aurora, RDS Proxy, ECS, SQS, or Redis back into this course demo.
- Keep human review before simulated/real staff escalation. The product must never claim that assistance was dispatched until an admin records it.
- Treat real SMS/call delivery as a separate, opt-in phase. It needs verified contact numbers, provider credentials, consent, budget, and a delivery-failure policy.
- Remove or disable controls that are intentionally out of scope rather than leaving a button that fails.
- Support both student registration/sign-in and guest/bystander alerts. Registration must never block the initial emergency alert.
- Keep notifications in simulation mode for this course demo. Every simulated staff alert must be labelled as recorded rather than delivered.
- Do not create staff portal accounts. Staff are contacted by the admin through the configured directory; the admin records acknowledgement/findings if they are received by call or in person.

## User-Facing Workflow After Completion

```text
Student / bystander taps help
  → alert is stored once, even after rapid repeat taps
  → optional campus place, callback, and details are saved
  → student can view current status using their alert token
  → admin signs in and claims the queue item
  → admin records contact / need verification
  → admin selects a mapped staff contact or medical team
  → system records simulated delivery (or a verified provider result)
  → staff acknowledges and reports findings
  → admin resolves or closes a false report with an audit trail
```

## Task List

### Phase 1: Make the current demo truthful and complete

#### Task 1: Define the deployed DynamoDB API contract

**Description:** Document the exact alert, contact, coverage, assignment, and event fields used by the deployed Lambda. Remove ambiguity between the old SQLAlchemy routes and the active DynamoDB routes.

**Acceptance criteria:**
- [ ] `docs/DEMO-API-CONTRACT.md` lists every supported demo endpoint and request/response shape.
- [ ] Each frontend action has exactly one supported API endpoint or is deliberately hidden.
- [ ] Contract identifies simulated notifications as simulation.

**Verification:**
- [ ] Endpoint contract smoke test executes every listed route.
- [ ] No frontend API call targets an undocumented deployed route.

**Dependencies:** None

**Likely files:** `app/routers/data_api_demo.py`, `app/dynamo_demo_repository.py`, `frontend/medical.js`, `docs/DEMO-API-CONTRACT.md`

**Estimated scope:** Medium

#### Task 2: Complete student alert details and safe status tracking

**Description:** Implement the guest-token-protected detail update route for place, landmark, callback number, and optional GPS data. Preserve the one-tap initial alert when a student cannot fill details.

**Acceptance criteria:**
- [ ] Student can submit details after one-tap alert creation.
- [ ] Wrong/missing guest token receives 403.
- [ ] Admin queue shows saved location/details.
- [ ] Location sharing is either tested end-to-end or disabled in the public UI.

**Verification:**
- [ ] Focused API tests cover valid, stale, and unauthorized guest updates.
- [ ] Browser flow: alert → details → admin queue shows details.

**Dependencies:** Task 1

**Likely files:** `app/routers/data_api_demo.py`, `app/dynamo_demo_repository.py`, `frontend/medical.js`, tests

**Estimated scope:** Medium

#### Task 3: Repair the admin action contract and audit trail

**Description:** Make claim, contact, verify, dispatch, resolve, and false-report closure use one consistent request shape and append clear audit events.

**Acceptance criteria:**
- [ ] Every admin action button succeeds with its UI payload.
- [ ] False-report closure requires and stores a clear reason.
- [ ] Stale version changes return an understandable 409 message.

**Verification:**
- [ ] API tests cover each transition and a stale-version conflict.
- [ ] Browser admin flow completes without a raw API error toast.

**Dependencies:** Task 1

**Likely files:** `app/routers/data_api_demo.py`, `app/dynamo_demo_repository.py`, `frontend/medical.js`, tests

**Estimated scope:** Medium

### Checkpoint A: Core student-to-admin flow

- [ ] Guest alert → add details → claim → verify → simulated dispatch → resolve works in the public site.
- [ ] Duplicate taps create one alert.
- [ ] No visible control produces a 404/405/422 because its deployed endpoint is absent.

### Phase 2: Make staff routing and response real inside the demo

#### Task 4: Implement admin-managed contacts and coverage

**Description:** Add DynamoDB routes for creating, editing, activating, and listing contacts, then map campus places to ordered staff contacts/shift coverage.

**Acceptance criteria:**
- [ ] Admin can add caretaker, warden, department, backup, and medical contacts.
- [ ] Admin can set day/night/all-hours availability and phone number.
- [ ] Admin can map one or more contacts to a campus place.
- [ ] Admin queue shows relevant suggested contacts but permits override.

**Verification:**
- [ ] API tests verify contact/coverage CRUD and role authorization.
- [ ] Browser test saves coverage for CSED Lab and receives the expected suggestion.

**Dependencies:** Checkpoint A

**Likely files:** `app/routers/data_api_demo.py`, `app/dynamo_demo_repository.py`, `frontend/medical.js`, `frontend/medical.html`, tests

**Estimated scope:** Large — split implementation into contact CRUD and coverage CRUD commits.

#### Task 5: Complete the admin-operated staff coordination slice

**Description:** Remove staff login/inbox UI. When an admin alerts a selected contact, record the simulated notification and provide admin controls to record a phone/in-person acknowledgement and findings.

**Acceptance criteria:**
- [ ] No staff account, inbox, or staff portal is required.
- [ ] Admin can record that a selected contact acknowledged the request.
- [ ] Admin can add staff findings to the alert timeline.

**Verification:**
- [ ] Browser test covers assignment, recorded acknowledgement, findings, and admin event visibility.

**Dependencies:** Task 4

**Likely files:** `app/routers/data_api_demo.py`, `app/dynamo_demo_repository.py`, `frontend/medical.js`, `frontend/medical.html`, tests

**Estimated scope:** Medium

#### Task 6: Remove unsupported messaging and registration paths, or implement them

**Description:** Choose a consistent demo boundary. Recommended default: hide self-registration and messaging because the campus demo uses guest alerts plus preconfigured admin/staff users.

**Acceptance criteria:**
- [ ] No visible button calls an absent endpoint.
- [ ] Authentication UI accurately describes supported account types.
- [ ] Demo limitation text is clear and non-alarming.

**Verification:**
- [ ] Browser console/network audit has no failed requests from normal portal actions.

**Dependencies:** Tasks 2–5

**Likely files:** `frontend/medical.js`, `frontend/medical.html`, `frontend/config.js`

**Estimated scope:** Small

### Checkpoint B: Full demo workflow

- [ ] Student/bystander → details → admin verification → nearest contact suggestion → staff acknowledgement/findings → resolution works.
- [ ] Admin can manage staff contacts and coverage from the live portal.
- [ ] All notifications are labelled simulated until a real provider is approved.

### Phase 3: Reliability, safety, and deployment quality

#### Task 7: Improve emergency-safe UI states

**Description:** Replace raw backend error strings with safe user messages, allow an intentional re-alert/escalation path, and stop queue refresh from interrupting admin work.

**Acceptance criteria:**
- [ ] Student receives actionable human-language error messages.
- [ ] Student can intentionally escalate an unresolved alert without accidental duplication.
- [ ] Admin selection/form input survives refresh.

**Verification:**
- [ ] Browser test covers offline/API error rendering and escalation.
- [ ] Accessibility keyboard checks pass for primary emergency actions.

**Dependencies:** Checkpoint B

**Likely files:** `frontend/medical.js`, `frontend/medical.css`, tests

**Estimated scope:** Medium

#### Task 8: Add operational safeguards for the deployed demo

**Description:** Add structured request/alert logging, an admin setup checklist, rate-limit documentation, and a clear operational status panel.

**Acceptance criteria:**
- [ ] Every alert/action has a request ID and audit event.
- [ ] Admin portal distinguishes simulation from delivery.
- [ ] Deployment runbook explains password rotation, tests, and rollback.

**Verification:**
- [ ] Lambda logs correlate an alert lifecycle by ID.
- [ ] Runbook can be followed on a clean browser session.

**Dependencies:** Checkpoint B

**Likely files:** `app/main.py`, `app/routers/data_api_demo.py`, `frontend/medical.js`, `docs/OPERATIONS.md`

**Estimated scope:** Medium

#### Task 9: Automate end-to-end checks in GitHub

**Description:** Add a focused test workflow that validates the deployed API contract and static frontend configuration without using the legacy ECS/RDS pipeline.

**Acceptance criteria:**
- [ ] Pull requests run the focused DynamoDB-route unit tests and frontend syntax check.
- [ ] GitHub Pages deployment runs only after its build checks pass.
- [ ] A post-deployment smoke test verifies the public page can preflight and create a demo alert in a protected test mode.

**Verification:**
- [ ] GitHub Actions shows green test and Pages deployment runs.

**Dependencies:** Tasks 1–8

**Likely files:** `.github/workflows/`, tests, deployment documentation

**Estimated scope:** Medium

### Checkpoint C: Release candidate

- [ ] All visible student/admin/staff actions are supported, intentionally hidden, or labelled out of scope.
- [ ] Full live workflow passes from GitHub Pages through Lambda and DynamoDB.
- [ ] No secrets are in Git; admin password is rotated from the demo value before any public use.

## Optional Phase 4: Real notifications

This phase should begin only after the college provides verified phone numbers, staff consent, an approved provider account, a budget, and an escalation policy.

#### Task 10: Introduce real notification delivery behind a provider interface

**Acceptance criteria:**
- [ ] A real provider result (sent/failed) is recorded separately from simulation.
- [ ] Failed delivery prompts an admin fallback call rather than claiming success.
- [ ] Provider keys are stored in Secrets Manager and never in GitHub Pages.

**Dependencies:** Checkpoint C and college approval

**Estimated scope:** Medium

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Sending a real alert during testing | High | Keep default notification mode simulated; use labelled test data only |
| Known demo password | High | Rotate it before demo sharing; use Secrets Manager, not source control |
| Frontend/API contract drifts | High | Contract document plus API/browser regression tests |
| Old ECS/RDS documentation causes wrong deployments | Medium | Clearly mark the DynamoDB Lambda demo as active; isolate/retire old workflow |
| CORS regression blocks emergency button | High | Browser preflight test for `Idempotency-Key` |
| No verified campus roster | High | Do not enable real delivery; prominently retain prototype notice |

## Confirmed Scope Decisions

1. Student self-registration and sign-in will be supported, alongside guest and bystander emergency alerts.
2. Notifications remain simulated for the demo. The UI and audit trail must never represent them as real SMS/calls.
3. Staff do not have individual portal logins. The admin coordinates them through the contact directory to avoid response delays.

## Decisions Still Needed Before Implementation

1. Should the legacy ECS/RDS files be archived/documented as unused, or retained for future coursework comparison?
