# Health & Readiness Monitoring

## Health Status Lifecycle
Components report one of five standardized statuses:
1. `HEALTHY`: Normal execution.
2. `DEGRADED`: Partial stream disconnect or elevated queue latency.
3. `UNHEALTHY`: Operational error requiring attention.
4. `HALTED`: Circuit breaker tripped or Risk Hard Stop active.
5. `UNKNOWN`: Initializing or missing health report.

## Probes
- Liveness Probe: `GET /health/live`
- Readiness Probe: `GET /health/ready`
- Dependencies Health: `GET /operations/dependencies`
- Operations Health: `GET /operations/health`
