# ADR-0001: Stateless HMAC Sessions and CSRF Hardening for EC2 Control Lambda

- **Status**: Accepted
- **Date**: 2026-09-15
- **Deciders**: Leader Agent / Architect

---

## Context & Problem Statement
The `python/EC2-StartStopStatus-Simple-Auth.py` template previously stored active user sessions in an in-memory dictionary (`sessions = {}`). In AWS Lambda, memory is ephemeral and execution contexts are not shared across concurrent instances or maintained across cold starts. Users were frequently logged out when requests were routed to different microVM containers. Furthermore, instance actions (`/start` and `/stop`) were executed via `GET` links without request method validation, creating Cross-Site Request Forgery (CSRF) and browser pre-fetch vulnerabilities.

---

## Decision Outcome
**Chosen Option**: Cryptographically signed stateless session tokens via HMAC-SHA256 and enforcement of HTTP `POST` for state-changing operations.

### Rationale
- Stateless tokens encoded as `base64url(payload).base64url(hmac_signature)` or `payload:signature` signed with `SESSION_SECRET` eliminate the need for an external session database (like DynamoDB) while ensuring 100% resilience across Lambda cold starts and horizontal scaling.
- Requiring HTTP `POST` for `/start` and `/stop` eliminates unintended triggers by web crawlers, browser link prefetching, and standard image-tag CSRF vectors.
- Standard library `urllib.parse` handles form data robustly without breaking on special characters.

### Implementation Details
- Module: `python/EC2-StartStopStatus-Simple-Auth.py`
- Token Structure: `f"{username}:{expiry_timestamp}:{signature}"` where signature is an HMAC-SHA256 digest verified in constant time with `hmac.compare_digest`.
- State operations `/start` and `/stop` only accept `POST` requests.
- Added standard HTTP security headers: `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`.

---

## Considered Alternatives

### Alternative 1: AWS DynamoDB Session Storage
- **Description**: Storing active tokens and TTL in a DynamoDB table.
- **Why discarded**: Adds external infrastructure dependency, IAM table permissions, and deployment friction for a standalone Lambda template designed to be self-contained.

### Alternative 2: Basic HTTP Authentication
- **Description**: Browser-native HTTP Basic Auth on every request.
- **Why discarded**: Poor UX on modern mobile/desktop browsers, lacks explicit logout mechanics, and sends credentials on every request rather than using short-lived signed tokens.

---

## Consequences

### Positive (Benefits)
- Completely serverless-native: sessions persist across cold starts and container recycling.
- Immune to simple GET-based CSRF attacks on EC2 start/stop operations.
- Zero extra external dependencies (uses Python standard library).

### Negative (Trade-offs / Compromises)
- Immediate server-side token revocation requires rotating `SESSION_SECRET` (which invalidates all active sessions). This is standard and acceptable for single-admin control panels.
