# Security Control Matrix

| Control ID | Standard | Requirement | Status | Evidence | Owner |
|---|---|---|---|---|---|
| ASVS-V1 | OWASP ASVS 5.0.0 | Architecture & Threat Modeling | PASS | `docs/THREAT_MODEL.md` | Security Lead |
| ASVS-V2 | OWASP ASVS 5.0.0 | Authentication & Session | PASS | `packages/governance/security.py` | Security Lead |
| ASVS-V4 | OWASP ASVS 5.0.0 | Access Control & RBAC | PASS | `packages/governance/security.py` | Security Lead |
| ASVS-V5 | OWASP ASVS 5.0.0 | Input Validation & Sanitization | PASS | `packages/governance/validation.py` | Core Team |
| ASVS-V14 | OWASP ASVS 5.0.0 | Configuration & Hardening | PASS | `infra/migrations/versions/012_security_hardening.py` | DevOps Lead |
| NIST-SSDF | NIST SSDF | Software Supply Chain Provenance | PASS | `packages/governance/sbom.py` | Security Lead |
| SLSA-L2 | SLSA | Artifact Checksums & Provenance | PASS | `docs/RELEASE_CANDIDATE.md` | DevOps Lead |
