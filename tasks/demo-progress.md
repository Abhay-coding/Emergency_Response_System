# Campus medical demo progress

- [x] Review current DynamoDB, API, student and admin workflow; preserve unrelated worktree changes.
- [x] Add demo-only alert and contact namespaces, contact outcomes and delays, and scoped reset.
- [x] Add student location capture, status polling and explicit demo labels.
- [x] Add admin queue overview, search, filters and demo dispatch progression.
- [x] Run focused tests and separate DynamoDB Local storage checks.
- [x] Run combined HTTP and DynamoDB Local workflow, fix failures, and retest (2 integration tests passed).
- [x] Exercise a local browser guest alert, manual location, admin verification, simulated contact, dispatch, team progress and student resolution; student viewport 390px showed no horizontal overflow.
- [x] In a local browser, test simulated GPS capture and refresh, denied-permission manual fallback, admin GPS map link, and 390px admin horizontal overflow.
- [x] Browser-check simulated GPS timeout, manual location persistence after refresh, and on-demand map iframe creation with a privacy notice. External map tiles have not been verified.
- [x] Browser-check an admin draft survives a concurrent location update and student status recovers after a simulated network failure.
- [x] DynamoDB Local HTTP test: a no-answer contact does not permit dispatch; a second accepted contact allows simulated dispatch and appears in the timeline.
- [x] DynamoDB Local HTTP test: register and sign in a fictional student, submit a signed-in alert, and verify the stored reporter association.
- [x] Browser-check student registration, signed-in alert, sign-out and admin sign-in; fixed the dialog retaining registration mode.
- [x] Browser-check reorganized admin detail tabs, keyboard arrow navigation, simulated dispatch history, and selected dispatch panel at 390px; fixed observed overflow.
- [x] Restrict runtime API overrides to loopback-only local development; test that a production page ignores hostile URL and storage overrides.
- [x] Browser-check demo-mode guard: isolated backend enables the alert; an incompatible backend leaves it disabled with a persistent warning.
- [x] Browser-check startup outage and reconnection: submission remains disabled during failure and becomes available when the isolated service returns.
- [x] API checks prevent unanswered contacts being shown to students as assigned teams; accepted demo team names are labelled fictional.
- [x] Broader network-isolated Linux suite: 46 passed, 2 DynamoDB Local tests skipped (run separately), 7 existing deprecation/pytest warnings.
- [x] Added an explicit block preventing the legacy SNS sender from sending when the isolated DynamoDB demo is enabled, even if SNS is configured; focused tests: 33 passed, 1 skipped.
- [x] Re-ran both DynamoDB Local integration tests after making default demo contacts and campus locations available without an AWS bootstrap secret; both passed. The temporary in-memory database was removed.
- [x] Admin staff acknowledgments and findings now use conditional version updates; focused tests and the DynamoDB Local HTTP workflow verify stale updates return 409.
- [x] Admin conditional actions and their activity entries now commit in one DynamoDB transaction; integration test forces an activity-write failure and verifies the state change rolls back. CDK's existing table read/write grant covers the underlying put/update permissions.
- [x] Demo contact attempts and delayed outcomes now commit with their activity entries; DynamoDB Local tests force activity-write failures and exercise simultaneous polling, confirming one recorded result.
- [x] Student registration reserves the normalized email and creates the profile atomically; a concurrent DynamoDB Local test confirms one account wins and can be found immediately. The HTTP workflow separately verifies registration and sign-in. Existing profiles remain readable.
- [x] Student timeline queries use consistent, paginated alert-partition reads; DynamoDB Local HTTP tests check every expected stage, timestamps, and repeated reads after resolution.
- [x] Added a loopback-only local demo launcher and run instructions. A local database test verifies first-time setup and preservation of an existing admin; an actual Windows server check verified demo configuration, admin login and the student page with a pre-seeded fictional admin.
- [x] Browser-checked admin location warnings for 250 m accuracy and unavailable accuracy; unconfirmed locations are labelled in the queue and detail view without inventing zero-metre precision.
- [x] Avoid repeated default-contact/place initialization on each request while retrying failed initialization; test covers both cases. Latest network-isolated suite: 46 passed, 3 local-database tests skipped there; all 3 passed separately against DynamoDB Local.
- [x] New simulated assignments retain the contact ID; the contacts section shows active assignments from the displayed queue and updates after resolution. Verified in a local browser and DynamoDB Local integration tests. Older records without contact IDs remain unchanged.
- [x] Added optional client-driven automatic presentation using the existing audited demo actions. Browser tests verified the complete saved progression and that a no-answer result stops before dispatch. The page must stay open; manual controls remain available.
- [x] Require a nonblank resolution note for final demo progression and a meaningful trimmed reason for false-report closure; focused tests and DynamoDB Local HTTP workflow passed.
- [ ] Complete verification states, safe urgent dispatch, timeline timestamps and persistence checks.
- [ ] Complete student/admin usability and responsive redesign; verify desktop and mobile with a browser.
- [ ] Test geolocation allowed, denied, unavailable and edits; test retries, concurrent admins and reset isolation.
- [ ] Run applicable automated checks and document remaining limitations and local run commands.

The user authorized pushing these changes to GitHub. Deployment and production-data deletion remain outside this verification.
