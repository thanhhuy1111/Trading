# Crypto Multi-Agent Trading Advisor — Campaign Plan

## Nguồn và phạm vi

Tài liệu campaign này được tạo trong Phase 4A từ
`/Users/phanthanhhuy/Downloads/CODEX_EXECUTION_PLAYBOOK.md` ngày 2026-07-24. Trước thời điểm
này repo chưa có `docs/campaign/CRYPTO_MULTI_AGENT_SYSTEM_PLAN.md`; vì vậy tài liệu này không
khẳng định thêm lịch sử ngoài playbook, Git và `docs/MULTI_AGENT_ADVISOR_PROGRESS.md`.

Mục tiêu MVP:

- symbol: `BTCUSDT`;
- timeframe: `4h`;
- Research, Shadow Trading và Paper Trading;
- Gemini 3.5 Flash là provider LLM dự kiến;
- Live Trading không thuộc phạm vi.

## Safety invariants

1. `LIVE_TRADING_ENABLED=False`.
2. `PRIVATE_EXCHANGE_API_ENABLED=False`.
3. Không dùng private exchange API, trading secret, real-order endpoint hay withdrawal permission.
4. Missing/error data phải được biểu diễn bằng `None` hoặc trạng thái an toàn, không thay bằng
   zero hoặc dữ liệu/lineage/confidence giả.
5. Mọi feature phải thỏa `feature_available_time <= prediction_as_of_time`; mọi target phải
   thỏa `target_time > prediction_as_of_time`.
6. Runtime model chỉ được load artifact có trạng thái `APPROVED`.
7. Test mới phải offline và deterministic.

## Thứ tự triển khai

| Bước | Nội dung | Trạng thái |
|---|---|---|
| 1 | Chuẩn hóa codebase | Hoàn thành trước campaign |
| 2 | Dữ liệu spot và futures | Hoàn thành |
| 3 | Feature pipeline | Hoàn thành |
| 4 | XGBoost | Đang thực hiện |
| 5 | Gemini 3.5 Flash | Chưa bắt đầu |
| 6 | Technical và Derivatives Agents | Chưa bắt đầu |
| 7 | Bull–Bear Debate | Chưa bắt đầu |
| 8 | Verification và Risk | Chưa bắt đầu |
| 9 | Manager Agent | Chưa bắt đầu |
| 10 | API và Dashboard | Chưa bắt đầu |
| 11 | Shadow Trading | Chưa bắt đầu |
| 12 | Paper Trading | Chưa bắt đầu |
| 13 | Thu thập dữ liệu thực nghiệm | Chưa bắt đầu |
| 14 | On-chain, news, macro và ETH | Chưa bắt đầu |
| 15 | Luận văn từ kết quả thực tế | Chưa bắt đầu |

## Phân rã Phase 4

Phase 4 phải chạy tuần tự và mỗi task chỉ thực hiện một vertical slice:

1. 4A — Research & Design.
2. 4B — Dataset & Labels.
3. 4C — Training & Walk-forward.
4. 4D — Approval & Artifact.
5. 4E — Runtime Serving & Final Verification.

Không chuyển sang Phase 5 trước khi toàn bộ acceptance criteria Phase 4 đạt và commit đã được
push lên `origin/main`.

## Workflow mỗi task

1. Kiểm tra repo, nhánh và năm commit gần nhất.
2. Đọc tài liệu campaign và phase hiện tại.
3. Research implementation, tests, contracts và dependencies.
4. Chốt scope, file plan, reuse plan, tests và acceptance criteria.
5. Implement vertical slice nhỏ nhất.
6. Chạy targeted Ruff, mypy và pytest.
7. Review `git diff --check`, `git diff --stat`, full diff và safety invariants.
8. Chạy full pytest, Ruff và mypy; không che giấu baseline failures.
9. Cập nhật `docs/campaign/PROGRESS.md`.
10. Commit và push trực tiếp `main`; không tạo branch hay PR.
