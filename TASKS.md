# Tasks Backlog

> Managed autonomously by the **Leader** agent.
> You do NOT need to edit this file manually unless you want to add or reorder tasks.
> You can simply tell your AI in chat what you want to build, and the Leader will break it down here.

## Invariant
- Maximum **1** task in progress (`[/]`) at any time.

---

## Tasks

<!--
Format:
- [ ] [task_slug] Task title — Description and acceptance criteria
- [/] [task_slug] Task in progress (max 1)
- [x] [task_slug] Task completed (approved by Reviewer and Security Reviewer)
- [-] [task_slug] Task blocked (requires human decision)
-->

- [x] **ec2_auth_hardening**: Refactor python/EC2-StartStopStatus-Simple-Auth.py with stateless HMAC sessions, POST state actions, robust parsing, transitional status colors, and security headers
- [x] **vpn_monitor_hardening**: Refactor python/check-vpn-on-EC2.py with safe auto-termination flag, bounded SSM polling, input validation, structured logging, and unit tests
- [x] **route53_acm_hardening**: Refactor python/Create-CLIENT-Route53-and-ACM.py with exact hosted zone matching, ACM polling, certificate idempotency, atomic Route53 batching, and unit tests
- [ ] **init_setup**: Initial project structure and setup baseline
