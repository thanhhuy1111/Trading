# Recommendation API (Phase 8)

`apps/api/routers/recommendations.py`, mounted in `apps/api/main.py` alongside the 26
pre-existing routers. Default wiring (`apps/api/deps.py`) reads market data from the offline
research cache (`packages/runtime/candles_cache.py`) - a missing cache file returns no
candles, never a network call.

## Endpoints

| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/recommendations/health` | none | Runtime-only health; independent of Postgres/Redis. |
| POST | `/recommendations/analyze` | `create:recommendation` | Full pipeline for one symbol. |
| POST | `/recommendations/scan` | `create:recommendation` | Full pipeline across up to 50 symbols. |
| GET | `/recommendations/{proposal_id}` | `read:recommendations` | Fetch a previously generated proposal (in-memory, bounded, ephemeral). |
| GET | `/readiness` | `read:recommendations` | Current six-axis `ReadinessStatus`. |
| POST | `/evidence/lookup` | `read:recommendations` | Exact-match evidence lookup by full 12-field key. |
| GET | `/strategy-portfolio/sleeves` | `read:recommendations` | List registered sleeves. |
| POST | `/strategy-portfolio/sleeves` | `manage:strategy_portfolio` | Register a sleeve. |
| GET | `/registries/{registry_name}/entries` | `read:recommendations` | List/filter one of the 7 Phase 3 registries. |
| POST | `/portfolio-risk/evaluate` | `read:recommendations` | Direct portfolio risk governor call. |
| GET | `/system/architecture-status` | `read:recommendations` | Architecture completion summary. |

## Auth

`apps/api/deps.py: get_current_principal` reads `X-Principal-Id` / `X-Roles` headers and
defaults to an anonymous `VIEWER`. This is a minimal, honest abstraction - not a real identity
provider - built on the pre-existing `packages.governance.security.SecurityManager` RBAC. A
real OAuth/JWT provider can replace the header extractor later without touching any endpoint's
permission check. New permissions added to `ROLE_PERMISSIONS`:
`read:recommendations`, `create:recommendation`, `manage:strategy_portfolio`.

## Error schema

`apps/api/error_schema.py` gives `PortError`, request-validation failures, and any
otherwise-unhandled exception a stable envelope: `{error_code, message, request_id,
reason_codes, details}`. `X-Request-ID` is read from the incoming request or generated, and
echoed back on every error response. `HTTPException` (403/404 raised directly by a route)
deliberately keeps FastAPI's default `{"detail": ...}` shape - 26 pre-existing routers already
depend on that exact contract, and Phase 8 does not change it app-wide.

## Testing

All 14 API tests (`tests/unit/test_recommendations_api.py`) run via FastAPI `TestClient` with
`app.dependency_overrides` - fixture candles, fresh in-memory evidence/portfolio stores per
test, an `ADMINISTRATOR` principal override. No live exchange or LLM call anywhere in the test
path.
