# Campus Medical Assistance: Product Brief

## Decision

Build a college-specific **cloud computing** emergency assistance flow, subject to a human operator and real campus contact roster being available. The first useful release must make an alert visible immediately, let the admin coordinate a response, and show the student what has and has not happened. The project must demonstrate cloud deployment, reliable event handling, persistence, and monitoring. Treat it as an academic prototype until the college validates staffing, contacts, and notification delivery.

## Who and why

- **Student needing help:** May be unable to complete a form. One tap should create a request.
- **Student witnessing an incident:** Needs a quick way to report someone else's medical emergency.
- **Admin on duty:** Reviews incoming reports, contacts the reporter, chooses nearby staff, and coordinates medical help.
- **Department or hostel staff:** Check the scene and report back to the admin.
- **Hostel caretaker and warden:** Are reachable according to a day/night duty roster. The admin decides when to alert them.

Today the app requires sign-in plus a multi-step form with title, urgency, description, and location. It has admin and responder roles, incident assignment, and status updates, but no staff directory, duty roster, live triage queue, or one-tap alert.

## Desired outcome

A student can create an alert with one tap, even when logged out. An on-duty admin sees and acknowledges it promptly, obtains or confirms the location, alerts appropriate nearby staff, and dispatches the medical team when indicated. A logged-out report is clearly marked as identity-unverified; the student can still see limited request progress through a private one-time session token. Every handoff is recorded.

## Success measures for a campus pilot

- Time from tap to server receipt and to admin acknowledgement.
- Percentage of requests with a usable location or successful callback.
- Percentage of staff alerts acknowledged and time to acknowledgement.
- Time from admin acknowledgement to medical-team dispatch when needed.
- Unacknowledged alerts and false-report decisions, reviewed by humans.

## Risks and guardrails

- No reply is not proof of a prank. Keep the request open and escalate per campus procedure.
- Guest identity is unverified, not automatically false. Abuse controls must not require a form or CAPTCHA before the first alert.
- Phone location needs permission and may be imprecise. Do not block submission while acquiring it.
- A browser dashboard alone cannot ensure a person is alerted when nobody is watching. The production workflow needs tested backup notification delivery and on-duty coverage.
- Show a direct campus emergency call option to the student. Do not imply the app has dispatched help until an actual person or integration confirms it.
- Limit access to sensitive incident data by role; record staff actions and contact attempts.
- Cloud components must have observable failures and recover after service restarts; a dashboard notification alone is insufficient for unattended alerts.

## Scope and anti-goals

The initial product is campus-only and limited to medical emergencies and suspected medical incidents. It is not a diagnosis tool, a general grievance/reporting portal, or a replacement for the college's emergency phone service. Automated prank scoring must not suppress alerts.

## Next step

Use the accompanying design in `docs/superpowers/specs/2026-11-06-campus-medical-response-design.md` to plan implementation after review.
