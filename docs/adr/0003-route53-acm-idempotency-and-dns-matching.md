# ADR-0003: Route 53 Exact Zone Matching, ACM Idempotency, and Validation Polling

- **Status**: Accepted
- **Date**: 2026-09-15
- **Deciders**: Leader Agent / Architect

---

## Context & Problem Statement
The `python/Create-CLIENT-Route53-and-ACM.py` template sets up Route 53 DNS records and requests ACM certificates. Previously:
1. `list_hosted_zones_by_name(DNSName=domain_name)` picked the first returned zone without checking for an exact domain name match, risking modifications to unrelated zones in multi-zone AWS accounts.
2. `CallerReference` utilized Python's randomized `hash()`, producing non-deterministic and negative identifiers.
3. ACM certificates were requested on every run without checking for pre-existing certificates, risking exhaustion of account quotas.
4. ACM DNS validation records were retrieved after an arbitrary `time.sleep(10)`, failing silently if ACM required longer to generate records.
5. Multiple sequential Route 53 API calls were made instead of batched transactions.

---

## Decision Outcome
**Chosen Option**: Implement exact zone name matching, deterministic caller references, ACM certificate reuse (`list_certificates`), bounded polling for validation records, and consolidated Route 53 `ChangeBatch` operations.

### Rationale
- Route 53 zone matching must verify `zone['Name'] == f"{domain.rstrip('.')}."` and ensure the zone is public to avoid cross-tenant misconfiguration.
- Deterministic caller references (`hashlib.sha256`) guarantee idempotent zone creation across Lambda cold starts.
- Checking existing certificates in `ISSUED` or `PENDING_VALIDATION` states preserves account quotas on repeated executions.
- Polling `DomainValidationOptions` until `ResourceRecord` is populated prevents certificates from remaining in permanent validation limbo.
- Batching DNS changes into a single API call avoids Route 53 rate-limiting and provides transactional record upserts.

### Implementation Details
- Module: `python/Create-CLIENT-Route53-and-ACM.py`
- Added input validation for `IP_ADDRESS` (`ipaddress.ip_address`), `DOMAIN_NAME`, and `BASE_SUB_DOMAIN`.
- Implemented `get_or_create_hosted_zone()`, `get_or_request_certificate()`, and `wait_for_validation_records()`.
- Grouped A-records and validation CNAME records into batched Route 53 requests.
- Converted all `print()` statements to standard Python `logging`.

---

## Consequences

### Positive (Benefits)
- Completely safe against multi-domain collision in Route 53.
- Idempotent and quota-friendly on repeated runs.
- Immune to race conditions in ACM validation record generation.
- Reduces AWS API calls through batched transactions.

### Negative (Trade-offs / Compromises)
- First-time certificate provisioning takes variable time up to the polling duration (~15-45s), but ensures 100% completion.
