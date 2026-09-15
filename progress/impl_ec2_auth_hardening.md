# Implementation Report: ec2_auth_hardening

- **Task**: `ec2_auth_hardening`
- **Module**: `python/EC2-StartStopStatus-Simple-Auth.py`
- **Tests**: `tests/test_ec2_simple_auth.py`
- **Status**: Implemented & Verified

---

## Changes Made

1. **Stateless HMAC-SHA256 Session Tokens**:
   - Replaced mutable in-memory dictionary `sessions = {}` with stateless, cryptographically signed tokens (`payload_b64.hmac_signature`) utilizing `SESSION_SECRET` and constant-time verification (`hmac.compare_digest`).
   - Token payload includes username and UTC expiry timestamp (`exp`).
   - Migrated from deprecated `datetime.utcnow()` to `datetime.now(timezone.utc)`.

2. **CSRF & Method Hardening for State Transitions**:
   - Converted `/start` and `/stop` controls from `GET` links (`<a href="...">`) to `POST` forms (`<form method="POST">`).
   - Enforced HTTP `POST` validation in `lambda_handler` for state actions, returning `405 Method Not Allowed` with `Allow: POST` header for any non-POST requests.

3. **Robust Form & Cookie Parsing**:
   - Implemented `parse_form_body()` utilizing `urllib.parse.parse_qs` to safely handle full percent-encoded strings, symbols, and base64 encoded event bodies.
   - Updated `get_cookie()` to case-insensitively parse headers via `http.cookies.SimpleCookie`.

4. **Transitional EC2 States & Error Prevention**:
   - Configured dedicated color/emoji indicators for `pending`, `stopping`, and `shutting-down` states (amber/orange) in addition to `running` (green) and `stopped` (red).
   - Validated array bounds on `Reservations` and `Instances` to prevent unhandled `IndexError` when queried instances do not exist.
   - Sanitized dynamic variables using `html.escape()` across all HTML renderers to eliminate XSS risks.

5. **Security Headers & Logging**:
   - Added standard security headers on all HTTP responses: `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, and `Cache-Control: no-cache, no-store, must-revalidate`.
   - Replaced raw `print()` statements with standard Python `logging`.
   - Extracted helper functions (`render_status_rows`, `handle_login`, `handle_ec2_action`, `is_authenticated`) ensuring all functions comply with `<= 50` lines and lines are `<= 100` characters.

---

## Test Verification
- Created `tests/test_ec2_simple_auth.py` with 29 test cases covering:
  - Token creation, validation, tamper detection, expiration, and invalid secret handling.
  - Form parsing with percent encoding, symbols, and base64 bodies.
  - Case-insensitive cookie header lookup.
  - Credential checks (happy path, wrong password, wrong user, unconfigured hash).
  - Lambda handler routing (login POST, logout session clearing, protected route gating, EC2 status/start/stop operations, 405 Method Not Allowed enforcement).
- All 29 unit tests pass cleanly:
  `Ran 29 tests in 0.003s — OK`
