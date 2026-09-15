# ADR-0002: Safe VPN Monitoring, Input Sanitization, and Opt-In EC2 Termination

- **Status**: Accepted
- **Date**: 2026-09-15
- **Deciders**: Leader Agent / Architect

---

## Context & Problem Statement
The `python/check-vpn-on-EC2.py` script monitors VPN connections via AWS Systems Manager (SSM) Run Command. Previously, any unhandled exception (e.g., IAM permission errors, SSM rate limiting, transient network timeouts) triggered immediate instance termination via `terminate_instances()`, creating an extreme risk of catastrophic data loss in production. Furthermore, `TARGET_IP` and `PORT` were interpolated directly into shell commands without validation, and SSM status polling broke on `Pending` or `Delayed` statuses.

---

## Decision Outcome
**Chosen Option**: Implement strict input validation, bounded SSM polling with full status lifecycle awareness, and safe opt-in instance auto-termination (`ENABLE_AUTO_TERMINATE`).

### Rationale
- Production instances must never be terminated due to script exceptions, missing environment variables, or transient AWS API failures. Auto-termination should only occur after confirmed test failure, failed restart, and failed retry, and must be guarded by an explicit environment flag (`ENABLE_AUTO_TERMINATE=true`).
- Validating `TARGET_IP` (IP format) and `PORT` (integer between 1 and 65535) mitigates command injection via environment variables.
- Bounded polling over `("Pending", "InProgress", "Delayed")` with configurable timeouts prevents infinite loops and Lambda execution freezes.

### Implementation Details
- Module: `python/check-vpn-on-EC2.py`
- Added input validation using `ipaddress` and integer bounds checks.
- Bounded SSM polling loop with timeout protection.
- Replaced `print()` with structured `logging`.
- Structured JSON response payload with explicit execution statuses (`HEALTHY`, `RECOVERED`, `UNHEALTHY`, `TERMINATED`, `ERROR`).

---

## Consequences

### Positive (Benefits)
- Eliminates accidental instance destruction from transient errors.
- Prevents remote command injection vectors.
- Resilient SSM command status tracking.

### Negative (Trade-offs / Compromises)
- Operators who rely on auto-termination must explicitly set `ENABLE_AUTO_TERMINATE=true`.
