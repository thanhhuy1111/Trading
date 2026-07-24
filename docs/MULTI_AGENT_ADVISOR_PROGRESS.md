# Crypto Multi-Agent Trading Advisor — Báo cáo tiến độ

> Tài liệu này là điểm khởi đầu cho bất kỳ ai (người hoặc AI agent) tiếp tục công việc trên
> một nhánh khác. Đọc xong file này là đủ để hiểu bối cảnh, quy ước, và bước tiếp theo mà
> không cần đọc lại lịch sử chat.

## 1. Bối cảnh

Dự án đang triển khai theo một kế hoạch 15 bước ("Crypto Multi-Agent Trading Advisor", dùng
Gemini 3.5 Flash làm lớp LLM diễn giải) mà người dùng cung cấp. Thứ tự triển khai chính thức
(mục §29 "Kết luận triển khai" của plan gốc):

1. Chuẩn hóa codebase
2. Hoàn thiện dữ liệu spot và futures
3. Xây feature pipeline
4. Huấn luyện và approve XGBoost
5. Tích hợp Gemini 3.5 Flash
6. Xây Technical và Derivatives Agents
7. Xây Bull–Bear Debate
8. Xây Verification và Risk
9. Xây Manager Agent
10. Xây API và Dashboard
11. Bật Shadow Trading
12. Bật Paper Trading
13. Thu thập dữ liệu thực nghiệm
14. Mở rộng on-chain, news, macro và ETH
15. Viết luận văn sau khi hệ thống có kết quả thực tế

Bước 1 coi như đã có sẵn từ trước (codebase hiện tại đã qua một đợt hoàn thiện kiến trúc
riêng — xem `docs/ARCHITECTURE_COMPLETION_REPORT.md`, `docs/FINAL_ACCEPTANCE_REPORT.md`).
Cách tiếp cận đã chọn: **làm từng bước một, có research + kế hoạch rõ ràng trước khi code**,
không cố làm toàn bộ 15 bước trong một lần.

**Lưu ý:** `plan.md` ở gốc repo là một tài liệu kiến trúc tổng quát cũ hơn, KHÔNG phải plan
15 bước này. File plan gốc của campaign này (`CRYPTO_MULTI_AGENT_SYSTEM_PLAN.md`) chưa được
lưu vào repo — nếu cần đối chiếu chi tiết, phải hỏi lại người dùng.

## 2. Trạng thái hiện tại

- **Nhánh làm việc:** `main` (theo yêu cầu người dùng — từ nay code thẳng trên `main`, không
  tạo branch riêng cho từng phase nữa, không mở PR trừ khi được yêu cầu rõ ràng).
- **Commit mới nhất liên quan:** `17be5ec` (Phase 2), `57fa5ba` (Phase 1) — cả hai đã ở trên
  `origin/main`.
- **Đã hoàn thành: Bước 2 và Bước 3** trong 15 bước (chi tiết ở mục 3).
- **An toàn giao dịch (bất biến, phải giữ nguyên ở mọi bước sau):**
  - `LIVE_TRADING_ENABLED=False`, `PRIVATE_EXCHANGE_API_ENABLED=False`
    (`packages/common/config.py`).
  - Không có API key sàn riêng tư nào được dùng — mọi connector chỉ gọi endpoint public,
    read-only.
  - Không bao giờ bịa dữ liệu: mọi trường hợp thiếu/lỗi dữ liệu phải trả `None` /
    `WARMING_UP` / `DEGRADED` / `UNHEALTHY` trung thực, không có fallback giả.
- **Kiểm tra chất lượng ở lần verify gần nhất:** `pytest tests/ -q` → 487 passed, 3 fail (đều
  là lỗi cũ không liên quan: 2 test integration bị chặn mạng do geo-restriction của Binance,
  1 test alembic migration thiếu file config — không phải do code mới). `ruff check .` sạch.
  `mypy packages/ apps/` → đúng 180 lỗi có sẵn từ trước, không phát sinh lỗi mới.

## 3. Chi tiết những gì đã xây (Bước 2 + Bước 3)

### Bước 2 — Dữ liệu futures/derivatives (Binance USDM Futures, public REST)

| File | Vai trò |
|---|---|
| `packages/market_data/derivatives_models.py` | Model `DerivativesSnapshot` — mark/index price, funding rate, open interest, long/short ratio, taker buy/sell ratio, futures basis (bps), `reason_codes` |
| `packages/market_data/derivatives_quality.py` | Tính basis (bps), xác định `DataQualityStatus` từ kết quả fetch từng phần |
| `packages/market_data/adapters/derivatives_base.py` | Protocol `DerivativesDataProvider` |
| `packages/market_data/adapters/binance_futures.py` | `BinancePublicFuturesDataProvider` — gọi 4 endpoint public của `fapi.binance.com`, không cần API key |
| `apps/api/routers/market_data.py` | `GET /market-data/derivatives/{symbol}`, cache TTL 30s (`settings.DERIVATIVES_CACHE_TTL_SECONDS`) |

### Bước 3 — Feature pipeline cho derivatives

| File | Vai trò |
|---|---|
| `packages/market_data/derivatives_history.py` | Cache lịch sử JSON append-only tại `data/research/derivatives/` (thư mục `data/` bị gitignore). Binance không hỗ trợ backfill lịch sử cho các endpoint `/futures/data/*`, nên lịch sử chỉ tích lũy dần qua các lần poll thật. Có dedup (5 phút/entry) và giữ tối đa 30 ngày. |
| `packages/features/derivatives_models.py` | `DerivativesFeatureSnapshot` — giống `FeatureSnapshot` nhưng lineage theo số lượng sample thay vì candle |
| `packages/features/derivatives_registry.py` | Registry riêng (`DerivativesFeatureRegistry`) — **không** dùng chung `feature_registry` gốc vì `FeatureCalculator` Protocol gốc bị "khoá cứng" kiểu `List[Candle]` dưới mypy strict mode, một calculator kiểu `List[DerivativesSnapshot]` không thoả structural typing |
| `packages/features/calculators/derivatives.py` | 3 calculator: `funding_rate_zscore_20`, `open_interest_roc_12`, `futures_basis_momentum_6` — mỗi cái trả `INSUFFICIENT_HISTORY` (không bịa số) khi chưa đủ `required_lookback` sample thật |
| `packages/features/derivatives_pipeline.py` | `DerivativesFeaturePipeline.compute()` — lọc chống rò rỉ dữ liệu tương lai (chỉ dùng snapshot có `exchange_timestamp <= as_of_time`), trạng thái WARMING_UP (thiếu lịch sử) / DEGRADED (lỗi thật) / VALID |
| `apps/api/routers/features.py` | `GET /features/derivatives/definitions`, `GET /features/derivatives/snapshots/latest?symbol=` |

## 4. Quy ước bắt buộc khi code tiếp (đã áp dụng nhất quán qua 2 bước trên)

- **Không bịa dữ liệu**: mọi adapter/calculator trả `Optional[...]`/`None` khi thiếu dữ liệu,
  không raise, không tự chế số liệu.
- **Chống rò rỉ dữ liệu tương lai (anti-lookahead)**: mọi pipeline tính feature phải lọc input
  theo `<= as_of_time` trước khi tính, có `model_validator` chặn trường hợp lineage timestamp
  vượt `as_of_time`.
- **Không tạo pipeline trùng lặp** nhưng cũng không ép hai loại dữ liệu khác nhau (candle vs.
  derivatives snapshot) dùng chung một pipeline nếu cấu trúc không khớp — xây pipeline song
  song nhỏ, dùng chung các model/Protocol thật sự generic.
- **Duck typing qua `typing.Protocol`** cho mọi adapter/calculator — không ép kế thừa.
- **Test offline 100%**: mock/monkeypatch mọi lời gọi mạng thật, dùng `tmp_path` cho mọi thứ
  đụng tới filesystem. Không có test nào phụ thuộc mạng thật (2 test cũ bị fail do
  geo-restriction là ngoại lệ đã biết, không mở rộng thêm).
- **Sau mỗi file mới**: chạy `ruff check <file>` và `.venv/bin/mypy <file>`, xác nhận lỗi mypy
  (nếu có) là lỗi có sẵn từ trước (so với baseline 180 lỗi hiện tại), không phải lỗi mới.
- **Không mở Pull Request** trừ khi được yêu cầu rõ ràng.
- **Không đụng tới** `LIVE_TRADING_ENABLED` / `PRIVATE_EXCHANGE_API_ENABLED` / bất kỳ API key
  sàn riêng tư nào.

## 5. Lệnh xác minh nhanh

```bash
# Cài dependency nếu venv mới/thiếu package
.venv/bin/pip install -e .

# Chạy toàn bộ test
.venv/bin/pytest tests/ -q

# Lint
ruff check .

# Type check
.venv/bin/mypy packages/ apps/
```

Kỳ vọng: test pass ~487 (+ test mới bạn thêm), đúng 3 fail cũ không liên quan, ruff sạch,
mypy đúng baseline 180 lỗi có sẵn (không tăng).

## 6. Kế hoạch tiếp theo — Bước 4: Huấn luyện & approve XGBoost

Đây là nền tảng cho Quantitative Agent — các bước sau (Technical/Derivatives Agent, Bull-Bear
debate...) đều cần model này làm input tín hiệu định lượng. Hướng đi dự kiến (chưa code, cần
research + plan mode trước khi triển khai):

1. **Label**: định nghĩa target dự đoán (vd. hướng return N-bar tới, hoặc phân loại
   tăng/giảm/đi ngang có ngưỡng).
2. **Feature đầu vào**: gộp feature candle hiện có (`packages/features/pipeline.py`) + feature
   derivatives vừa xây (Bước 3).
3. **Walk-forward split**: theo đúng khuôn mẫu `packages/retraining/price_projection.py` đã
   dùng cho Ridge regression — tránh lookahead, đánh giá out-of-sample thật.
4. **Cổng approve nghiêm ngặt**: model chỉ "approved" nếu vượt baseline (random/majority-class)
   trên MỌI fold walk-forward — giữ đúng tinh thần "không fallback bịa confidence" đã áp dụng
   cho `trend-projection` (endpoint này từng bỏ hẳn EMA-slope vì không có edge thật ngoài mẫu).
5. **Lưu artifact** model đã approve (tương tự cách `price_projection.py` lưu artifact JSON),
   để Quantitative Agent (bước sau) đọc và phục vụ mà không cần train lại runtime.

Trước khi code Bước 4, nên research trong repo: `packages/retraining/` (đã có framework nào
để mở rộng?), xem `scikit-learn`/`xgboost` đã cài trong venv chưa, có chuẩn lưu artifact chung
nào cần theo không.
