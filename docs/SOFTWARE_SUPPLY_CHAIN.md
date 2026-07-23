# Software Supply Chain Security

## Supply Chain Principles
- Pinned direct dependencies in `pyproject.toml` and `package.json`.
- Lockfile integrity checksums verified during CI builds.
- Automatic CycloneDX Software Bill of Materials (SBOM) generation on release.
- Immutable Git commit release candidate tagging.
