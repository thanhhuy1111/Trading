# Software Bill of Materials (SBOM) Policy

## Format & Requirements
- Specification: CycloneDX v1.4 (JSON format).
- Automated generation via `packages.governance.sbom.sbom_generator`.
- Artifact checksums computed using SHA-256 algorithm.
- Exposed via API endpoint `GET /security/sbom`.
