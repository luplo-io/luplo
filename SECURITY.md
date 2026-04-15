# Security Policy

## Supported versions

luplo is pre-1.0 software. Only the latest release receives security fixes.

| Version | Supported |
|---------|-----------|
| 0.0.x   | Yes       |

## Reporting a vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Email **security@luplo.io** with:

- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if you have one)

## Response timeline

- **Acknowledge**: within 48 hours
- **Assessment**: within 7 days
- **Fix (critical)**: within 7 days of assessment
- **Fix (other)**: within 30 days of assessment

## Disclosure

We practice coordinated disclosure. Once a fix is released, we will:

1. Publish a security advisory on GitHub
2. Credit the reporter (unless they prefer anonymity)

## Scope

luplo stores engineering decisions which may include sensitive architectural
details, business logic, and compliance-relevant data. We take data integrity
and access control seriously even at this early stage.

Areas of particular interest:

- SQL injection via search queries or item fields
- Authentication bypass in Remote mode (OAuth/JWT)
- Unauthorized access to audit logs
- Data leakage across projects in multi-project setups
