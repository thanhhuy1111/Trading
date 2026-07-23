# Container Hardening Policy

## Hardening Directives
- Non-root user execution (`USER appuser`).
- Read-only root filesystem (`read_only: true`).
- Dropped Linux capabilities (`cap_drop: [ALL]`).
- No privileged mode (`privileged: false`).
- No Docker socket mounting (`/var/run/docker.sock` forbidden).
