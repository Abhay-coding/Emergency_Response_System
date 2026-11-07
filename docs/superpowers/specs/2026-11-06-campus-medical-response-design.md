# Campus Medical Response Design

## Intent

Make it possible for a student at this college to request medical assistance with one tap, or for another student to report an incident quickly. A human admin verifies and coordinates the response. The UI should never force a person in distress to describe symptoms, choose priority, or wait for location permission before the alert is created.

This is a **cloud computing project**. The design builds on the existing FastAPI, SQLAlchemy, and plain HTML/CSS/JavaScript app and its AWS ECS/RDS direction. The existing form can remain available as an optional detail path, but the primary student action becomes **Get medical help**.

## Cloud architecture and demonstration

- **Web/API:** Containerized FastAPI and frontend on AWS ECS Fargate behind an HTTPS Application Load Balancer, continuing the repository's current deployment direction. Keep at least two API tasks for the cloud demonstration; do not rely on process-local state for claims, timers, or notification status.
- **Durable data:** RDS PostgreSQL stores alerts, staff coverage and shifts, messages, acknowledgements, delivery attempts, and an append-only action history. Apply versioned Alembic migrations to preserve existing incidents. The current `create_all` startup behavior is insufficient for changing existing tables.
- **Asynchronous delivery:** Publish a durable notification/escalation job after the alert transaction. A cloud worker processes jobs, checks the persisted acknowledgement state before escalation, and records delivery results. Use a managed queue with retries and dead-letter handling (proposed: Amazon SQS) plus a college-approved outbound channel adapter. The timer must survive API or worker restarts and duplicate messages must be harmless.
- **Staff/admin updates:** Browser UI can use short polling first; the authoritative state remains in RDS. Polling continues after reconnect and missed events remain visible. A later real-time transport is optional.
- **Monitoring and operations:** Emit structured, privacy-conscious logs and metrics for tap-to-receipt latency, unacknowledged alerts, queue age, failed notifications, and worker errors to CloudWatch. Provide alarms for missed acknowledgement and delivery failure, and document a deployment/demo path. Store secrets in the managed secret store already referenced by the ECS task definition. Local Docker/SQLite behavior is for development only.
- **Cloud proof:** The project should include an architecture diagram, deployable infrastructure/configuration, and a demo showing an alert crossing API, database, queue/worker, admin portal, and staff acknowledgement, including a failed-delivery or timeout case.

## Scope and priorities

1. **Student alert and acknowledgement:** One tap creates a medical alert whether the student is signed in or logged out. The student immediately sees a request ID, submission state, and a direct campus emergency call action. A second tap must not create accidental duplicate open requests. Guest identity is shown to the admin as unverified.
2. **Bystander report:** Another student can report an incident they witnessed, identifying the patient only if known. The admin sees that the reporter is a bystander and obtains the patient's location and condition through them.
3. **Admin triage:** On-duty admins get a prominent queue of new and unacknowledged alerts with elapsed time, reporter contact, location confidence, and communication history. An admin claims an alert, contacts the reporter by phone or in-app short messages, records verification, and can override the normal order for an urgent or unanswered report.
4. **Local staff and medical handoff:** Admin sees suggested nearby departments or hostel staff from a maintained campus directory. The admin can alert one or several staff accounts, call their saved numbers, track acknowledgement, reassign, and dispatch the medical team. Staff record what they found. Hostel caretakers are contacted **after admin review**, with on-duty day/night contacts first and the warden as escalation.
5. **Missed-alert safety:** All on-duty admins receive the new alert. If none acknowledges within a configurable short interval (initial pilot default: 60 seconds), a tested out-of-band notification goes to a configured backup campus contact. The student's screen continues to offer the direct campus emergency phone action. An unconfigured or failed notification is shown as failed, never as delivered.

## Confirmed campus places

- CSED Lab; Library; C Block; B Block; F Block; G Block; Main Gate.
- A, O, B, C, and D hostels.
- G, N, Q, PG1, and PG2 girls' hostels.
- Electrical, Computer, and Electronics departments.

Keep the location names editable by admins. The same letter in a block and hostel is a different location. An admin configures which department or hostel staff cover each place and in what order. Names alone do not establish physical distance, so the app must not claim to have calculated the nearest staff until the college enters coverage or map data. For the first version, **suggested nearby staff** means the location's configured coverage list, with manual override.

## Student journey

1. A registered student may sign in before an emergency and optionally store a callback phone number. Registration and account setup are outside the emergency path. A logged-out student can still tap **Get medical help**, and the direct campus emergency phone action is always available.
2. Student opens the app and taps a large **Get medical help** button. The API records an alert immediately with time, source (`self`), `location_unknown` until proven otherwise, and an idempotency key. It stores reporter ID if authenticated; otherwise it records `guest` and returns a secret session token for limited follow-up access. The server stores only a hash of that token.
3. After submission, the app asks for device location. If granted, it sends coordinates, accuracy, and capture time as a location update. Geolocation is optional and subject to HTTPS and browser permission. The existing `Permissions-Policy` currently blocks it and must be changed narrowly for the application origin.
4. The screen offers a short campus-place picker, a free-text room or landmark, and an optional short description. Any of these may be supplied later. Selecting a known place is preferred over assuming a GPS point identifies an indoor room.
5. Student sees **Received**, then **Admin reviewing**, then actual dispatch progress. A guest can check only this request's limited status and can add optional callback details using the secret session token; the token does not expose staff notes, other students' reports, or medical records. If the server request fails, show a clear failure state and the campus emergency call action; never claim help was requested.
6. Bystander starts from **Report someone else's emergency**. The report is sent promptly with their identity; the place picker and description are encouraged but not a pre-submit gate.

## Admin, staff, and caretaker journey

1. A new alert enters the admin queue immediately with sound/visual indication while the portal is open. On-duty admins may claim it; the claim is visible to other admins.
2. The admin checks identity, location, and what happened by calling the reporter or sending brief in-app prompts. The admin records each attempt and whether details were confirmed. **No answer is not classified as a prank.**
3. The admin may alert nearby staff while verifying when warranted, and may dispatch the medical team immediately for an urgent report or when an unanswered request still appears serious. The admin cannot be forced to wait for a verification flag.
4. Staff receive a minimal incident summary, acknowledge or decline, and report their findings. Admin can call from the directory and record a manual acknowledgement when contact happens by phone.
5. For a hostel incident, admin chooses the on-duty caretaker after review, with the warden available as backup. Shift assignments and contact details are maintained by admins. For other locations, admin chooses configured department staff.
6. The admin records medical team dispatch and resolution. A report can be marked false/prank only after review, with a reason and audit trail. That action does not delete the original alert.

## State and data

- Separate **response status** (`new`, `acknowledged`, `checking`, `staff_alerted`, `medical_dispatched`, `resolved`, `closed_false_report`) from **verification** (`unverified`, `confirmed_need`, `confirmed_false`). Do not infer verification from silence.
- Incident stores optional reporter ID, `self` or `bystander`, guest/authenticated identity state, timestamps, optional callback number snapshot, optional campus place, free-text location, optional coordinates/accuracy/timestamp, optional details, admin owner, and relevant staff assignment. Guest follow-up token hashes and expiry are separate from ordinary account sessions.
- A campus place has a type (building, department, hostel, gate), display name, optional coordinates, and ordered staff coverage. Staff have role, department/hostel affiliation, phone, active status, and duty schedule. Medical team contacts are managed in the same directory.
- Incident events record actor, time, action, channel, outcome, and note. The queue and student status derive from persisted state. Duplicate submissions are handled by idempotency key and a visible open-alert check.
- Access control: authenticated students see reports they personally submitted, including bystander reports; patient identity alone grants no access. Guests see only a limited status projection of the alert tied to their unguessable, expiring session token. Staff see only alerts sent to them, admins see all. Server-side permissions govern every state transition and message; frontend hiding is insufficient. The current responder role can see all reports, so this behavior must be corrected.
- Use additive endpoints and migrations for the one-tap contract because the current incident schema requires title, description, category, and location and its status model cannot represent human verification. Preserve legacy rows and map old statuses deliberately. Correct the existing status audit event so it captures the old value before mutation.

## Notification and failure behavior

- In-app queue updates must be near real time (server-sent events or short polling). Staff alerts also need acknowledgement and a retry/escalation path.
- Browser sound and desktop notifications are supplemental. Production use requires an actual out-of-band backup (for example, a college-approved SMS or call provider), tested with real on-duty contacts. Configuration must distinguish **not configured**, **send failed**, **sent**, and **acknowledged**.
- If there is no on-duty admin, no working provider, or no confirmed campus emergency number, the system must show an operational warning to staff and keep the student's direct call option prominent. It must not present an unstaffed prototype as guaranteed emergency coverage.
- The escalation worker retries transient sends, records each attempt, and moves exhausted jobs to a visible failure queue. It must check the current alert state immediately before sending so a late acknowledgement does not trigger a stale backup alert.
- During local development, simulated notification delivery must be clearly labeled as simulated and have verbose logs without exposing medical details or secrets.
- Guest submissions receive server-side abuse controls such as per-session and IP rate limits and duplicate suppression, but no pre-submit CAPTCHA or required identity form. If a request is rejected or cannot reach the server, the UI must clearly show failure and offer the direct campus emergency call route. Guest status and optional location/contact updates require the secret token; no public incident lookup by numeric ID.

## Approaches considered

1. **Phone-only verification:** Fast for a speaking student, but fails when the student cannot answer and gives no in-app history.
2. **In-app questions only:** Accessible without a phone call, but depends on the student remaining able to use the app.
3. **Flexible human triage (chosen):** Admin can call, message, alert local staff, dispatch the medical team, and record results. More engineering work, but fits the college's department and hostel staffing model and the user's request for admin flexibility.

## Boundaries

This is a campus medical assistance product, not medical diagnosis or automated triage. No automated model determines whether an alert is real or suppresses it. It does not promise ambulance dispatch or caretaker notification unless a real action succeeds. Patient medical history, parent notifications, and public incident feeds are outside the first release.

## Acceptance checks

- Signed-in and logged-out students can generate a persisted alert with one tap and no required form fields or location permission.
- A guest gets only a limited, token-protected status view and cannot read other incidents; expired or guessed tokens reveal nothing.
- Admin sees it without manually refreshing and can claim, contact, alert staff, and record medical dispatch; other admins see the claim.
- Bystander reports are identifiable as such; student and reporter access stays limited to their own requests.
- Denied or timed-out geolocation still leaves a valid alert; the student can add a campus place later.
- Hostel alerts do not notify caretakers until an admin sends them; the correct shift is suggested.
- No reply leaves the alert open and eligible for escalation; false-report closure requires a reason and is audited.
- Failed notification delivery and missing backup configuration are visible, not shown as successful.
- Existing auth and incident flows keep working, with migrations for the new state and directory.

## Builder decisions left open

Choose the smallest reliable near-real-time transport and notification provider integration supported by the college's deployment. The college must supply real staff contacts, schedules, a campus emergency number, and tested backup recipient details before live use. The listed place names are initial data; exact coverage order is an admin-maintained configuration.
