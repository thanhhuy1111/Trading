# Database Security Policy

## Hardening Controls
- Parameterized SQL queries via SQLAlchemy ORM (zero string concatenation).
- Strict role isolation: Separate migration role and application runtime role.
- Connection pooling with statement timeouts.
- Alembic schema migration locking and checksum validation.
