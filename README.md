# 🐍 Lambda Templates by Lechu

Welcome to my collection of AWS Lambda functions! ⚡ This repository contains production-hardened Python scripts designed for cloud automation, infrastructure orchestration, compute management, and network monitoring in AWS environments.

⚠️ **Disclaimer**: These scripts are provided as-is for educational and automation purposes. Always thoroughly test in your own staging environment before production deployment.

---

## 📋 Table of Contents

- [🔧 Infrastructure Automation: Route53 & ACM](#-infrastructure-automation-route53--acm)
- [🖥️ Compute Management: EC2 Web Controller](#️-compute-management-ec2-web-controller)
- [🌐 Network Monitoring: VPN Auto-Recovery](#-network-monitoring-vpn-auto-recovery)
- [🧪 Automated Testing](#-automated-testing)
- [🏛️ Architecture Decision Records (ADRs)](#️-architecture-decision-records-adrs)
- [🚀 Quick Start & Deployment Guide](#-quick-start--deployment-guide)
- [🔒 Security Best Practices](#-security-best-practices)
- [🤝 Contributing & Standards](#-contributing--standards)

---

## 🔧 Infrastructure Automation: Route53 & ACM

**File:** `python/Create-CLIENT-Route53-and-ACM.py`  
**Test Suite:** `tests/test_create_route53_acm.py`

Automates Route 53 DNS setup and dual-region SSL certificate provisioning (regional and `us-east-1` for CloudFront) for new clients or applications.

### Key Hardened Features:
- 🎯 **Exact Hosted Zone Matching**: Resolves public hosted zones by exact domain match (`zone['Name'] == f"{domain}."`), preventing accidental modification of unrelated prefix zones in multi-tenant accounts.
- ⚡ **Atomic Batch Operations**: DNS A-records are committed in a single atomic `ChangeBatch` transaction, minimizing Route 53 API roundtrips and preventing throttling.
- 🔄 **Certificate Idempotency**: Inspects ACM via `list_certificates` before requesting new certificates, reusing existing `ISSUED` or `PENDING_VALIDATION` certificates to prevent account quota exhaustion.
- ⏱️ **Bounded Validation Polling**: Polls `DomainValidationOptions` until `ResourceRecord` is populated, avoiding race conditions and permanent pending validation states.
- 🛡️ **Input Sanitization**: Validates `IP_ADDRESS` via standard `ipaddress.ip_address` and strictly validates domain formats.

### Environment Variables:
```bash
DOMAIN_NAME=example.com
BASE_SUB_DOMAIN=client1
IP_ADDRESS=1.2.3.4
LOG_LEVEL=INFO  # Optional: DEBUG, INFO, WARNING, ERROR
```

### IAM Permissions Required:
- `route53:ListHostedZonesByName`
- `route53:CreateHostedZone`
- `route53:ChangeResourceRecordSets`
- `acm:ListCertificates`
- `acm:RequestCertificate`
- `acm:DescribeCertificate`

---

## 🖥️ Compute Management: EC2 Web Controller

**File:** `python/EC2-StartStopStatus-Simple-Auth.py`  
**Test Suite:** `tests/test_ec2_simple_auth.py`

Provides a lightweight, serverless web interface for starting, stopping, and monitoring the status of an EC2 instance with built-in authentication.

### Key Hardened Features:
- 🎫 **Stateless HMAC-SHA256 Sessions**: Replaces ephemeral in-memory storage with cryptographically signed session tokens (`SESSION_SECRET`). Sessions persist across Lambda cold starts and horizontal container scaling without requiring DynamoDB.
- 🛡️ **CSRF & Method Protection**: State-changing endpoints (`/start`, `/stop`) strictly enforce HTTP `POST` requests, preventing unintended triggers by web crawlers, browser prefetching, or cross-site image attacks (`405 Method Not Allowed` on `GET`).
- 🔐 **Secure Form Parsing**: Uses standard `urllib.parse` and `SimpleCookie` to reliably handle special characters in credentials (`@`, `&`, `=`, `#`) and case-insensitive cookie headers.
- 🚦 **Transitional Status Indicators**: Visual indicators for all instance states:
  - 🟢 `running` (Green)
  - 🟡 `pending`, `stopping`, `shutting-down` (Amber)
  - 🔴 `stopped` (Red)
  - ⚪ `terminated` (Gray)
- 🔒 **Security Headers & XSS Defense**: Emits `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, and sanitizes dynamic output with `html.escape()`.

### Environment Variables:
```bash
INSTANCE_ID=i-1234567890abcdef0
AWS_ALT_REGION=us-west-2
AUTH_USERNAME=admin
AUTH_PASSWORD_HASH=your_sha256_hash_of_password
SESSION_SECRET=random_32_byte_hex_string
LOG_LEVEL=INFO
```

### IAM Permissions Required:
- `ec2:DescribeInstances`
- `ec2:DescribeInstanceStatus`
- `ec2:StartInstances`
- `ec2:StopInstances`

---

## 🌐 Network Monitoring: VPN Auto-Recovery

**File:** `python/check-vpn-on-EC2.py`  
**Test Suite:** `tests/test_check_vpn_ec2.py`

Monitors VPN health on an EC2 instance via AWS Systems Manager (SSM) Run Command and initiates automatic service restarts upon failure.

### Key Hardened Features:
- 🛡️ **Safe Opt-In Auto-Termination**: Prevents accidental instance destruction. Auto-termination is disabled by default (`ENABLE_AUTO_TERMINATE=false`) and will never trigger on script exceptions, IAM issues, or transient SSM network timeouts.
- 💉 **Command Injection Defense**: Strict validation of `TARGET_IP` (`ipaddress.ip_address` or secure hostname regex) and `PORT` (integer 1–65535) before constructing remote shell commands.
- ⏳ **Bounded SSM Polling**: Correctly handles `Pending`, `InProgress`, and `Delayed` SSM execution states with monotonic timeout limits to prevent infinite execution freezes.
- 📊 **Structured Status Payload**: Returns explicit operational statuses (`HEALTHY`, `RECOVERED`, `UNHEALTHY`, `TERMINATED`, `CONFIG_ERROR`, `ERROR`).

### Environment Variables:
```bash
EC2_INSTANCE_ID=i-1234567890abcdef0
TARGET_IP=10.0.1.100
PORT=22
VPN_TEST_COMM="nc -w3 -zvvv"                          # Optional
VPN_RESTART_COMM="sudo systemctl restart strongswan"  # Optional
ENABLE_AUTO_TERMINATE=false                           # Set to "true" to allow termination
LOG_LEVEL=INFO
```

### IAM Permissions Required:
- `ssm:SendCommand`
- `ssm:GetCommandInvocation`
- `ec2:TerminateInstances` (Only required if `ENABLE_AUTO_TERMINATE=true`)

---

## 🧪 Automated Testing

This repository includes a comprehensive unit test suite with 100% standard library compatibility (runs without external pip dependencies via mocked Boto3 clients):

```bash
# Run the entire test suite
python3 -m unittest discover tests

# Run specific test modules
python3 -m unittest tests/test_ec2_simple_auth.py
python3 -m unittest tests/test_check_vpn_ec2.py
python3 -m unittest tests/test_create_route53_acm.py
```

All 63 unit tests pass in `< 0.02s` and cover happy paths, edge cases, tamper detection, and error handling.

---

## 🏛️ Architecture Decision Records (ADRs)

Key architectural decisions and security models are documented under `docs/adr/`:
- [ADR-0001: Stateless HMAC Sessions and CSRF Hardening](docs/adr/0001-stateless-hmac-sessions-and-csrf-protection.md)
- [ADR-0002: Safe VPN Monitoring, Input Sanitization, and Opt-In EC2 Termination](docs/adr/0002-safe-vpn-monitoring-and-ssm-execution.md)
- [ADR-0003: Route 53 Exact Zone Matching, ACM Idempotency, and Validation Polling](docs/adr/0003-route53-acm-idempotency-and-dns-matching.md)

---

## 🚀 Quick Start & Deployment Guide

### Deployment via AWS CLI

1. **Package your chosen function:**
   ```bash
   zip -j function.zip python/EC2-StartStopStatus-Simple-Auth.py
   ```

2. **Create the Lambda function:**
   ```bash
   aws lambda create-function \
     --function-name ec2-control \
     --runtime python3.11 \
     --role arn:aws:iam::123456789012:role/lambda-execution-role \
     --handler EC2-StartStopStatus-Simple-Auth.lambda_handler \
     --zip-file fileb://function.zip \
     --environment Variables='{
       "INSTANCE_ID":"i-1234567890abcdef0",
       "AUTH_USERNAME":"admin",
       "AUTH_PASSWORD_HASH":"your_sha256_hash",
       "SESSION_SECRET":"your_32_byte_hex"
     }'
   ```

3. **Generate password hash and session secret:**
   ```bash
   # SHA-256 password hash
   echo -n "YourSecurePassword" | shasum -a 256

   # Secure session secret
   openssl rand -hex 32
   ```

---

## 🔒 Security Best Practices

- **Secrets Management**: Store sensitive credentials in AWS Secrets Manager or encrypted Lambda environment variables (AWS KMS).
- **Least Privilege**: Attach IAM policies scoped strictly to the target instance IDs and hosted zone IDs.
- **Serverless Resilience**: Stateless tokens ensure that horizontal container scaling does not disconnect active sessions.
- **Network Isolation**: Deploy Lambda functions within VPC private subnets when interacting with internal VPN endpoints.

---

## 🤝 Contributing & Standards

Contributions are welcome! Please follow these standards:
- **Style**: Follow PEP 8 guidelines (max 100 characters per line, max 50 lines per function).
- **Typing**: Include type annotations and `from __future__ import annotations`.
- **Testing**: Add corresponding unit tests in `tests/` and verify all tests pass before submitting pull requests.

---

*Made with ❤️ by Lechu*
