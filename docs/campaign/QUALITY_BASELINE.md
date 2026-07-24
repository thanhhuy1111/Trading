# Campaign Quality Baseline

## Baseline được bàn giao

Nguồn: `CODEX_EXECUTION_PLAYBOOK.md` và `docs/MULTI_AGENT_ADVISOR_PROGRESS.md`.

| Check | Baseline gần nhất | Quy tắc |
|---|---:|---|
| `pytest tests/ -q` | 487 passed, 3 failed | Không tăng lỗi; ba lỗi cũ phải được nhận diện riêng |
| `ruff check .` | clean | Phải giữ clean |
| `mypy packages/ apps/` | 180 errors | Không được tăng số lỗi |

Ba lỗi pytest cũ được ghi nhận:

- hai integration tests bị Binance geo-restriction;
- một integration test Alembic thiếu config;
- không được sửa ngoài scope chỉ để thay đổi baseline.

## Trạng thái môi trường quan sát ở đầu Phase 4A

- Repo không có `.venv/` tại root.
- `python3` và `pytest` trên `PATH` dùng Python 3.10, trong khi `pyproject.toml` yêu cầu
  Python `>=3.12`.
- `ruff` có trên `PATH`.
- executable/module `mypy` không có trên `PATH` tại thời điểm khảo sát.
- `scikit-learn`, `joblib`, `numpy`, `pandas` import được từ Python trên `PATH`.
- `xgboost` chưa import được và chưa được khai báo trong `pyproject.toml`.

Các quan sát trên là trạng thái môi trường, không thay thế baseline bàn giao. Mọi task phải
ghi đúng command thực tế đã chạy và không được claim `.venv`/mypy/full-suite pass nếu công cụ
không tồn tại.

Để verify Phase 4A trên Python version được project hỗ trợ, một `.venv` Python 3.12.12 cục bộ
đã được tạo từ `.[dev,research]`. Thư mục này đã bị gitignore và không phải thay đổi source.

## Phase 4A verification hiện tại

| Check thực tế | Kết quả |
|---|---|
| Targeted tests liên quan retraining/features/registry/lookahead | 40 passed |
| `.venv/bin/pytest tests/ -q` | 489 passed, 12 skipped, 1 failed |
| `.venv/bin/ruff check .` | clean |
| `.venv/bin/mypy packages/ apps/` | 180 errors in 67 files |

Full-suite failure còn lại là
`tests/integration/test_db_migration.py::test_alembic_migration_lifecycle`, do thiếu
`infra/migrations/alembic.ini`; đây là lỗi Alembic đã có trong baseline. Hai network tests
Binance được skip trong environment này thay vì fail. Không có source file nào thay đổi trong
Phase 4A, nên mypy giữ đúng baseline 180.

## Safety baseline

`packages/common/config.py` khai báo:

```python
LIVE_TRADING_ENABLED: bool = False
PRIVATE_EXCHANGE_API_ENABLED: bool = False
FEATURE_FLAGS_LIVE_TRADING: bool = False
```

Mỗi task phải review diff để xác nhận không thay đổi các mặc định này, không thêm private
exchange API và không thêm real-order path.

Runtime settings được đọc trong Phase 4A cũng trả cả ba giá trị là `False`.

## Phase 4B verification

| Check thực tế | Kết quả |
|---|---|
| Targeted dataset/derivatives/adapter tests | 55 passed |
| `.venv/bin/pytest tests/ -q` | 512 passed, 12 skipped, 1 failed |
| `.venv/bin/ruff check .` | clean |
| `.venv/bin/mypy packages/ apps/` | 180 errors in 67 files |

Full-suite failure vẫn là missing `infra/migrations/alembic.ini`; không có regression mới.
Ba runtime safety settings vẫn `False`.

## Phase 4C verification

| Check thực tế | Kết quả |
|---|---|
| `tests/unit/test_xgboost_training.py` | 15 passed |
| `.venv/bin/pytest tests/ -q` | 527 passed, 12 skipped, 1 failed |
| `.venv/bin/ruff check .` | clean |
| `.venv/bin/mypy packages/ apps/` | 180 errors in 67 files |

Full-suite failure vẫn là missing `infra/migrations/alembic.ini`; không có regression mới.
XGBoost 3.3.0 chạy trong Python 3.12 `.venv`; ba safety settings vẫn `False`.

## Phase 4D verification

| Check thực tế | Kết quả |
|---|---|
| Focused registry/approval/compatibility tests | 38 passed |
| `.venv/bin/pytest tests/ -q` | 534 passed, 12 skipped, 1 failed |
| `.venv/bin/ruff check .` | clean |
| `.venv/bin/mypy packages/ apps/` | 180 errors in 67 files |

Full-suite failure vẫn là missing `infra/migrations/alembic.ini`; không có regression mới.
Approval tests chỉ ghi artifacts dưới `tmp_path`; không có model weight persistent trong repo.
Ba safety settings vẫn `False`.

## Phase 4E verification

| Check thực tế | Kết quả |
|---|---|
| `tests/unit/test_xgboost_runtime.py` | 7 passed |
| `.venv/bin/pytest tests/ -q` | 541 passed, 12 skipped, 1 failed |
| `.venv/bin/ruff check .` | clean |
| `.venv/bin/mypy packages/ apps/` | 180 errors in 67 files |

Full-suite failure vẫn là missing `infra/migrations/alembic.ini`; không có regression mới.
Runtime tests offline, artifacts chỉ dưới `tmp_path`, không có network/private API/order path.
Ba safety settings vẫn `False`.

## Phase 5 verification

| Check thực tế | Kết quả |
|---|---|
| Provider/LLM/chat compatibility tests | 60 passed |
| `.venv/bin/pytest tests/ -q` | 554 passed, 12 skipped, 1 failed |
| `.venv/bin/ruff check .` | clean |
| `.venv/bin/mypy packages/ apps/` | 180 errors in 67 files |

Full-suite failure vẫn là missing `infra/migrations/alembic.ini`. Provider tests hoàn toàn
offline; không có Gemini call thật, secret, private exchange API hoặc live-trading change.

## Phase 6 verification

| Check thực tế | Kết quả |
|---|---|
| Specialist/runtime focused tests | 13 passed |
| `.venv/bin/pytest tests/ -q` | 560 passed, 12 skipped, 1 failed |
| `.venv/bin/ruff check .` | clean |
| `.venv/bin/mypy packages/ apps/` | 180 errors in 67 files |

Full-suite failure vẫn là missing `infra/migrations/alembic.ini`. Specialist tests hoàn toàn
offline; synthetic approved-runtime fixture chỉ ghi artifact dưới `tmp_path`. Không có model
persistent, Gemini call thật, private exchange API, order path hoặc live-trading change.

## Phase 7 verification

| Check thực tế | Kết quả |
|---|---|
| Offline debate tests | 6 passed |
| `.venv/bin/pytest tests/ -q` | 566 passed, 12 skipped, 1 failed |
| `.venv/bin/ruff check .` | clean |
| `.venv/bin/mypy packages/ apps/` | 180 errors in 67 files (baseline) |

Full-suite failure vẫn là known missing Alembic config. Debate providers are deterministic
test doubles; no network, private API, order path or live-trading change.
