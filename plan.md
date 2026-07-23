1. Mục tiêu hệ thống

Không nên đặt mục tiêu đơn giản là “tối đa hóa lợi nhuận”. Mục tiêu đúng nên là:

Maximize ExpectedReturn−λ
1
	​

×CVaR−λ
2
	​

×MaxDrawdown−λ
3
	​

×TradingCost−λ
4
	​

×ModelUncertainty

Tức là hệ thống phải:

Tạo lợi nhuận sau phí, funding, spread và trượt giá.
Hạn chế drawdown và nguy cơ cháy tài khoản.
Tự nhận diện khi chiến lược mất hiệu quả.
Tự giảm vốn hoặc ngừng giao dịch khi thị trường bất thường.
Không phụ thuộc vào một mô hình, một chiến lược hoặc một sàn.
Có thể giải thích vì sao mở lệnh, giữ lệnh hoặc đóng lệnh.

Không có hệ thống nào bảo đảm lợi nhuận. “Xịn nhất” trong trading nghĩa là hệ thống có khả năng sống sót lâu, kiểm soát rủi ro tốt và chỉ tăng vốn khi có bằng chứng thống kê đủ mạnh.

2. Nguyên tắc kiến trúc quan trọng nhất
Không để LLM trực tiếp tự do đặt lệnh

Hệ thống nên chia thành ba tầng quyền lực:

Tầng	Vai trò	Quyền đặt lệnh
Intelligence Agents	Phân tích và đề xuất giao dịch	Không
Risk Governor	Kiểm tra rủi ro, cấp hạn mức	Có quyền phủ quyết
Execution Engine	Gửi, sửa, hủy và theo dõi lệnh	Chỉ thực thi lệnh hợp lệ

LLM phù hợp để:

Phân tích tin tức và sự kiện.
Chuẩn hóa thông tin phi cấu trúc.
Phản biện lý do giao dịch.
Giải thích quyết định.
Phát hiện mâu thuẫn giữa các agent.

LLM không nên trực tiếp:

Tính PnL chính thức.
Tính số lượng lệnh.
Tự thay đổi leverage.
Bỏ qua stop-loss.
Gọi API sàn không qua Risk Engine.
Quyết định dựa trên văn bản tự do.

Các tác vụ số học phải do code deterministic, mô hình thống kê hoặc ML chuyên biệt thực hiện.

3. Kiến trúc tổng thể
Market Data / On-chain / News / Account Data
                    │
                    ▼
        Data Quality & Feature Platform
                    │
        ┌───────────┴────────────┐
        ▼                        ▼
  Alpha Agents              Context Agents
  - Trend                   - Market Regime
  - Mean Reversion          - News/Sentiment
  - Breakout                - On-chain
  - Order Book              - Macro/Event
  - Funding/Basis
        │                        │
        └───────────┬────────────┘
                    ▼
             Critic Agents
        - Phản biện tín hiệu
        - Kiểm tra dữ liệu
        - Phát hiện xung đột
                    │
                    ▼
             Meta Allocator
        - Tổng hợp tín hiệu
        - Chấm điểm cơ hội
        - Phân bổ vốn
                    │
                    ▼
             Risk Governor
        - Exposure limits
        - Drawdown control
        - Liquidity control
        - Kill switch
                    │
                    ▼
            Execution Engine
        - Order routing
        - Limit/market/TWAP
        - Partial-fill handling
        - Retry/idempotency
                    │
                    ▼
            Position Manager
        - Stop-loss
        - Take-profit
        - Signal decay
        - Regime exit
                    │
                    ▼
       Audit, Monitoring & Learning

Binance, Bybit và Coinbase đều cung cấp API giao dịch cùng dữ liệu thời gian thực qua REST/WebSocket; tuy nhiên mỗi sàn có cách xác thực, giới hạn kết nối, trạng thái lệnh và môi trường thử nghiệm khác nhau, vì vậy cần xây dựng adapter riêng cho từng sàn.

4. Hệ thống agent đề xuất
Nhóm A — Data Intelligence
Agent	Nhiệm vụ
Market Data Agent	Thu thập candle, trade, ticker, order book
Derivatives Data Agent	Funding, open interest, basis, liquidation
On-chain Agent	Exchange inflow/outflow, whale movement, network activity
News Agent	Phân tích tin tức, thông báo sàn, sự kiện token
Data Guardian	Phát hiện missing data, duplicate, outlier, stale timestamp

Data Guardian phải có quyền đóng băng toàn bộ tín hiệu nếu dữ liệu không còn đáng tin cậy.

Ví dụ điều kiện dừng:

WebSocket mất kết nối.
Order book bị lệch sequence.
Giá giữa hai nguồn lệch bất thường.
Timestamp chậm quá giới hạn.
Số dư nội bộ không khớp số dư trên sàn.
Không nhận được cập nhật trạng thái lệnh.

Binance cung cấp diff-depth stream để duy trì local order book và user data stream để nhận các trạng thái như NEW, TRADE, CANCELED, REJECTED; hệ thống cần xử lý đầy đủ cả partial fill thay vì chỉ giả định lệnh được khớp toàn bộ.

Nhóm B — Market Context
1. Regime Detection Agent

Phân loại thị trường:

Trending up.
Trending down.
Sideway.
High volatility.
Low volatility.
Liquidity crisis.
Event-driven.
Flash crash hoặc market dislocation.

Đầu vào:

Volatility.
ADX/trend strength.
Return autocorrelation.
Volume profile.
Spread và order-book depth.
Funding và open interest.
Cross-asset correlation.
Stablecoin flow.

Kết quả của agent này quyết định chiến lược nào được phép hoạt động.

Ví dụ:

Regime	Chiến lược được ưu tiên
Trending	Trend-following, breakout
Sideway	Mean reversion
High volatility	Giảm size, breakout có xác nhận
Liquidity crisis	Ngừng mở lệnh
Funding cực đoan	Funding/basis, contrarian có kiểm soát
2. Event Risk Agent

Theo dõi:

Listing/delisting.
Sự cố blockchain.
Hack hoặc exploit.
Stablecoin depeg.
Thay đổi tokenomics.
Thông báo bảo trì sàn.
Quyết định lãi suất và dữ liệu vĩ mô lớn.
Biến động bất thường liên quan ETF hoặc tổ chức.

Agent này không nhất thiết dự đoán hướng giá. Nó có thể chỉ phát tín hiệu:

{
  "risk_level": "critical",
  "affected_assets": ["BTC", "ETH"],
  "action": "reduce_exposure",
  "valid_until": "2026-07-23T02:00:00Z"
}
Nhóm C — Alpha Agents
1. Trend Agent

Sử dụng:

Multi-timeframe momentum.
Moving average slope.
Breakout confirmation.
Volatility-adjusted trend.
Cross-sectional momentum.

Phù hợp khung thời gian 15 phút đến vài ngày.

2. Mean Reversion Agent

Sử dụng:

Z-score.
Bollinger deviation.
VWAP deviation.
Statistical spread.
Short-term liquidation spike.
Order-book exhaustion.

Chỉ hoạt động khi Regime Agent xác nhận thị trường sideway hoặc quá bán/quá mua ngắn hạn.

3. Breakout Agent

Tìm:

Range compression.
Volume expansion.
Open-interest expansion.
Order-book thinning.
Volatility breakout.

Phải có cơ chế phát hiện breakout giả.

4. Microstructure Agent

Phân tích dữ liệu tick và order book:

Order-book imbalance.
Trade imbalance.
Bid–ask spread.
Depth concentration.
Cancel-to-trade ratio.
Aggressive buyer/seller flow.
Short-horizon adverse selection.

Nghiên cứu gần đây cho thấy order-flow imbalance, spread và các đặc trưng order book có thể mang tín hiệu ngắn hạn, nhưng maker strategy có thể chịu adverse selection khi cung cấp thanh khoản cho dòng lệnh có thông tin.

5. Funding/Basis Agent

Tìm cơ hội từ:

Funding rate quá cao hoặc quá thấp.
Chênh lệch spot–perpetual.
Chênh lệch kỳ hạn.
Funding divergence giữa các sàn.

Chiến lược này có thể hướng tới market-neutral, nhưng vẫn phải tính:

Phí giao dịch hai chiều.
Funding thực nhận.
Slippage.
Rủi ro sàn.
Khả năng lệch hedge.
Rủi ro thanh lý từng leg.
6. Cross-Asset Agent

Phân tích quan hệ:

BTC → ETH → altcoin.
BTC dominance.
Sector rotation.
Correlation breakdown.
Lead–lag giữa các sàn.
Stablecoin dominance.

Không nên triển khai cross-exchange arbitrage trong giai đoạn đầu vì yêu cầu vốn phân tán, kiểm soát chuyển tiền và rủi ro sàn phức tạp hơn nhiều.

Nhóm D — Decision and Governance
1. Critic Agent

Mỗi đề xuất giao dịch phải bị phản biện:

Tín hiệu có dùng dữ liệu tương lai không?
Dữ liệu có còn mới không?
Chi phí có làm mất lợi thế không?
Agent khác có tín hiệu ngược chiều không?
Mô hình có đang ngoài vùng dữ liệu đã học không?
Thị trường có sự kiện rủi ro không?
Có position tương quan cao đang mở không?

Critic Agent không tạo alpha. Nhiệm vụ của nó là tìm lý do không nên giao dịch.

2. Meta Allocator Agent

Nhận tín hiệu chuẩn hóa:

{
  "symbol": "BTCUSDT",
  "direction": "LONG",
  "expected_return_bps": 42,
  "confidence": 0.71,
  "horizon_minutes": 240,
  "invalidation_price": 64200,
  "estimated_cost_bps": 8,
  "max_entry_slippage_bps": 5,
  "regime": "TREND_UP",
  "feature_timestamp": "...",
  "model_version": "trend-v17"
}

Sau đó tính:

NetEdge=
i
∑
	​

w
i
	​

×CalibratedEdge
i
	​

−Fee−Spread−Slippage−Funding−UncertaintyPenalty

Chỉ giao dịch khi:

Net edge dương.
Edge lớn hơn một ngưỡng an toàn so với chi phí.
Có đủ thanh khoản.
Không vi phạm portfolio risk.
Tín hiệu không quá cũ.

Trọng số agent không cố định. Meta Allocator cập nhật trọng số dựa trên:

Regime hiện tại.
Hiệu quả gần đây.
Calibration accuracy.
Drawdown của từng chiến lược.
Tương quan giữa các agent.
Độ tin cậy dữ liệu.
5. Risk Governor — bộ phận quan trọng nhất

Risk Governor phải là service độc lập, không phụ thuộc vào LLM.

Giới hạn ban đầu đề xuất
Chỉ tiêu	Mức khởi đầu thận trọng
Rủi ro tối đa mỗi giao dịch	0,25–0,5% NAV
Tổng rủi ro các lệnh đang mở	1,5–2% NAV
Lỗ tối đa trong ngày	1,5% NAV
Lỗ tối đa trong tuần	4% NAV
Drawdown cảnh báo	5%
Drawdown đóng băng hệ thống	8–10%
Leverage giai đoạn đầu	1x, tối đa 2x
Tỷ trọng tối đa một tài sản	15–20% NAV
Tỷ trọng nhóm tài sản tương quan	30–40% NAV
Lệnh mới sau chuỗi thua	Giảm size 25–50%

Đây là thông số khởi tạo để kiểm thử, không phải mức cố định.

Position sizing

Kích thước vị thế:

Size=min(VolatilityTarget,FractionalKelly,LiquidityCap,PortfolioLimit,AgentConfidenceCap)

Nên sử dụng fractional Kelly, chẳng hạn 10–25% Kelly lý thuyết, thay vì full Kelly.

Hard risk rules

Không agent nào được ghi đè các quy tắc:

Không đặt lệnh khi dữ liệu stale.
Không tăng vị thế đang lỗ nếu chiến lược không cho phép từ trước.
Không mở lệnh nếu khoảng cách thanh lý không đủ an toàn.
Không sử dụng cross margin trong giai đoạn đầu.
Không mở position mới khi daily loss limit đã chạm.
Không mở lệnh khi spread hoặc slippage vượt ngưỡng.
Không giao dịch token ngoài whitelist.
Không thay đổi leverage trong khi lệnh đang thực thi.
Không mở hai chiến lược ngược chiều mà không netting rõ ràng.

Cross margin khiến các vị thế dùng chung collateral; khoản lỗ của một vị thế có thể ảnh hưởng giá thanh lý của các vị thế khác, và hiệu ứng này có thể không được mô phỏng đầy đủ trong backtest hoặc dry run.

Kill switch

Tự động ngừng hệ thống khi:

NAV giảm quá giới hạn.
Không đối soát được vị thế.
Sàn trả về quá nhiều lỗi.
Giá lệch giữa các nguồn.
Order rejection tăng đột biến.
Slippage thực tế cao hơn mô hình.
Model drift nghiêm trọng.
Risk service hoặc database lỗi.
Không thể hủy lệnh.
API key xuất hiện từ IP không hợp lệ.

Kill switch phải có hai mức:

Soft stop: không mở lệnh mới, quản lý lệnh đang mở.
Hard stop: hủy toàn bộ lệnh chờ và đóng vị thế theo chính sách khẩn cấp.
6. Logic mở và đóng lệnh
Luồng mở lệnh
Nhận market snapshot.
Data Guardian xác nhận dữ liệu hợp lệ.
Regime Agent phân loại thị trường.
Các Alpha Agent phát tín hiệu.
Critic Agent phản biện.
Meta Allocator tính NetEdge.
Risk Governor xác định số lượng tối đa.
Execution Engine tính phương án đặt lệnh.
Gửi lệnh với client_order_id duy nhất.
Theo dõi acknowledgment, partial fill và final fill.
Đối soát position nội bộ với sàn.
Luồng đóng lệnh

Một vị thế có thể đóng bởi nhiều nguyên nhân:

Loại exit	Mô tả
Hard stop	Giá chạm giới hạn mất mát
Volatility stop	Stop dựa trên ATR hoặc realized volatility
Take profit	Đạt mục tiêu lợi nhuận
Trailing stop	Bảo vệ lợi nhuận đang có
Time stop	Tín hiệu không chạy đúng trong thời gian dự kiến
Signal decay	Expected edge giảm xuống dưới ngưỡng
Signal reversal	Alpha đảo chiều
Regime exit	Chế độ thị trường thay đổi
Portfolio exit	Tổng rủi ro hoặc tương quan tăng cao
Event exit	Xuất hiện tin tức nghiêm trọng
Infrastructure exit	Mất dữ liệu hoặc lỗi sàn

Không nên chỉ dùng một stop-loss cố định theo phần trăm.

7. Execution Engine

Execution Engine nên viết bằng Go hoặc Rust, trong khi nghiên cứu và mô hình có thể dùng Python.

Chức năng bắt buộc
Market order.
Limit order.
Post-only.
IOC/FOK khi sàn hỗ trợ.
TWAP/VWAP.
Smart order slicing.
Cancel/replace.
Partial-fill management.
Retry có idempotency.
Rate-limit budgeting.
Reconnect WebSocket.
Sequence reconciliation.
Position reconciliation.
Dead-man switch.

WebSocket Binance có giới hạn kết nối và connection có thể hết hiệu lực sau 24 giờ; rate limit cũng có nhiều loại theo từng khoảng thời gian. Connector vì vậy phải chủ động reconnect, theo dõi quota và không retry mù quáng.

Chọn loại lệnh

Execution Agent tính:

ExecutionScore=FillProbability−SlippagePenalty−AdverseSelectionRisk−DelayPenalty

Ví dụ:

Edge ngắn hạn, biến động mạnh: ưu tiên market/IOC với size nhỏ.
Edge dài hơn, spread rộng: limit hoặc sliced order.
Order book mỏng: giảm size hoặc bỏ giao dịch.
Giá chạy khỏi vùng entry: không đuổi giá nếu NetEdge không còn đủ.
8. Nền tảng dữ liệu
Các loại dữ liệu
Nhóm	Dữ liệu
Spot	OHLCV, trades, order book
Derivatives	Funding, OI, mark price, liquidation, basis
Account	Balance, position, order, fill, fee
Cross-exchange	Price, spread, funding divergence
On-chain	Inflow/outflow, whale transfer, active address
News	Tin tức, thông báo sàn, social sentiment
Operational	Latency, reject rate, disconnect, API quota
Kiến trúc lưu trữ
ClickHouse: tick, trade, order-book events.
PostgreSQL/TimescaleDB: orders, positions, portfolio, audit.
S3/MinIO: raw data, model artifacts, backtest outputs.
Redis: cache, distributed locks, latest state.
Kafka/Redpanda: event streaming.
Feature Store: version hóa đặc trưng.
MLflow: model registry và experiment tracking.

Mỗi bản dữ liệu phải có:

Source.
Exchange timestamp.
Received timestamp.
Sequence ID.
Symbol mapping.
Schema version.
Data quality flag.

Không được âm thầm sửa dữ liệu lịch sử. Mọi correction phải có version.

9. Backtest đúng chuẩn

Một backtest chỉ dùng candle và giả định khớp lệnh tại close price gần như không đủ cho hệ thống này.

Simulator phải mô phỏng
Maker/taker fee.
Bid–ask spread.
Slippage theo size.
Partial fill.
Latency.
Order rejection.
Cancel delay.
Funding.
Mark price.
Liquidation.
Minimum quantity và tick size.
Sàn mất kết nối.
Order book không đủ thanh khoản.
Cơ chế stop thực tế.
Chênh lệch giữa signal time và fill time.
Quy trình đánh giá
Train
  ↓
Validation
  ↓
Walk-forward testing
  ↓
Locked out-of-sample
  ↓
Shadow trading
  ↓
Paper trading
  ↓
Small-capital live
  ↓
Capital ramp

Phải kiểm tra lookahead bias vì việc tính toàn bộ indicator trên một dataframe lịch sử có thể vô tình sử dụng dữ liệu tương lai.

Ngoài Sharpe thông thường, nên dùng:

Deflated Sharpe Ratio.
Probability of Backtest Overfitting.
Sortino.
Calmar.
Maximum drawdown.
CVaR/Expected Shortfall.
Profit factor.
Expectancy.
Turnover.
Cost sensitivity.
Performance theo regime.

Deflated Sharpe Ratio điều chỉnh selection bias do thử nhiều chiến lược và ảnh hưởng của phân phối lợi nhuận không chuẩn; PBO được thiết kế để đánh giá xác suất backtest bị overfit.

Không chỉ dùng testnet

Testnet/demo phù hợp kiểm tra API và lifecycle của lệnh, nhưng không đại diện đầy đủ cho thanh khoản và hành vi thị trường thật. Bybit lưu ý demo trading không hỗ trợ đầy đủ mọi API; tài liệu Freqtrade cũng cảnh báo sandbox có order book, liquidity và hành vi giao dịch khác thị trường thật.

Cần bổ sung shadow execution:

Nhận dữ liệu live thật.
Tạo lệnh giả lập.
Ước tính fill dựa trên order book thật.
Không gửi lệnh lên sàn.
So sánh giá dự kiến và giá có thể khớp thực tế.
10. Danh mục chiến lược triển khai

Không nên bắt đầu với quá nhiều chiến lược.

Giai đoạn 1

Universe:

BTC.
ETH.
Một số tài sản top liquidity được whitelist.

Thị trường:

Spot trước.
Perpetual chỉ sau khi hệ thống ổn định.

Chiến lược:

Multi-timeframe trend.
Volatility breakout.
Mean reversion có regime filter.
Funding filter.
Portfolio risk overlay.
Giai đoạn 2

Bổ sung:

Order-book imbalance.
Funding/basis market-neutral.
Cross-sectional momentum.
Dynamic strategy allocation.
Long/short perpetual với leverage thấp.
Giai đoạn 3

Bổ sung sau cùng:

Cross-exchange arbitrage.
Statistical pairs.
Maker strategy.
Options volatility.
Reinforcement learning.
Agent tự phát hiện chiến lược mới.

Không nên đưa reinforcement learning vào giai đoạn đầu. RL dễ học hành vi khai thác lỗi simulator thay vì học lợi thế thị trường thực.

11. Cơ chế tự học

Hệ thống không được tự thay model production ngay sau khi train.

Model lifecycle
Candidate Model
      ↓
Offline validation
      ↓
Adversarial validation
      ↓
Shadow deployment
      ↓
Champion–Challenger
      ↓
Human/Policy approval
      ↓
Limited production
      ↓
Full production
Champion–Challenger
Champion đang giao dịch.
Challenger chạy song song nhưng không đặt lệnh.
So sánh trên cùng dữ liệu và cùng execution assumptions.
Chỉ promote khi challenger tốt hơn một cách ổn định.
Có thể tự rollback nếu hiệu quả suy giảm.
Drift detection

Theo dõi:

Feature drift.
Prediction drift.
Confidence calibration.
Win rate theo regime.
Slippage drift.
PnL attribution.
Tương quan giữa các agent.
Khoảng cách dữ liệu hiện tại với tập train.

Khi drift:

Giảm position size.
Chuyển agent sang shadow.
Retrain.
Chạy validation.
Chỉ khôi phục sau khi đạt gate.
12. Hạ tầng kỹ thuật đề xuất
Thành phần	Công nghệ
Quant research	Python, Polars, NumPy, PyTorch, LightGBM/CatBoost
Distributed agents	Ray hoặc service riêng
Workflow dài hạn	Temporal
Execution	Go hoặc Rust
Message bus	Kafka/Redpanda
Tick database	ClickHouse
Transaction database	PostgreSQL
Cache/state	Redis
Object storage	S3/MinIO
Model registry	MLflow
Monitoring	Prometheus, Grafana
Tracing	OpenTelemetry
Secrets	Vault hoặc cloud KMS
Deployment	Kubernetes sau MVP
CI/CD	GitHub Actions/GitLab CI
Infrastructure	Terraform

Ray hỗ trợ cơ chế restart/retry cho actor khi cấu hình, nhưng mặc định actor không tự restart; do đó state quan trọng vẫn phải lưu ngoài process và mọi tác vụ gửi lệnh phải idempotent.

Tách môi trường
Research.
Backtest.
Staging.
Paper.
Live-small.
Live-production.

Tuyệt đối không dùng chung:

API key.
Database giao dịch.
Redis state.
Namespace Kafka.
Secrets.
Portfolio.
13. Bảo mật
API key
Chỉ bật read và trade.
Tắt withdrawal.
IP allowlist.
Dùng sub-account riêng.
Giới hạn số vốn trong tài khoản bot.
Key cho production không xuất hiện trong máy nghiên cứu.
Không lưu secret trong source code.
Rotate key định kỳ.
Mỗi sàn một key riêng.
Mỗi môi trường một key riêng.

Coinbase khuyến nghị IP allowlist và giới hạn permission cho API key; Binance cũng yêu cầu IP restriction trong một số trường hợp và khuyến nghị không bật withdrawal cho bot giao dịch.

Audit log

Mọi quyết định phải lưu:

Input snapshot ID.
Tín hiệu từng agent.
Model version.
Prompt version nếu dùng LLM.
Risk calculation.
Order payload.
Exchange response.
Fill.
Fee.
PnL.
Lý do exit.
Người hoặc service thay đổi cấu hình.

Audit log phải append-only.

14. Dashboard vận hành
Portfolio dashboard
NAV.
Realized/unrealized PnL.
Drawdown.
Gross/net exposure.
Leverage.
Asset concentration.
Correlation exposure.
Daily risk budget.
Agent dashboard
PnL từng agent.
Hit rate.
Expectancy.
Sharpe/Sortino.
Calibration.
Signal count.
Rejection reason.
Drift score.
Agent đang production/shadow/disabled.
Execution dashboard
Fill ratio.
Maker/taker ratio.
Slippage.
Latency p50/p95/p99.
Rejection rate.
Cancel failure.
WebSocket health.
Internal position so với exchange position.
Incident dashboard
Data stale.
API error.
Risk breach.
Model drift.
Exchange outage.
Kill-switch state.
Manual override history.
15. Lộ trình xây dựng 36 tuần
Giai đoạn	Thời gian	Kết quả
0. Thiết kế và pháp lý	2 tuần	PRD, universe, risk policy, venue policy
1. Data platform	4 tuần	Market data, order book, account stream
2. Backtest simulator	5 tuần	Event-driven simulation, fee/slippage/funding
3. Alpha agents V1	6 tuần	Trend, breakout, mean reversion, regime
4. Meta + Risk Engine	4 tuần	Consensus, sizing, hard limits, kill switch
5. Execution Engine	4 tuần	Order state machine, reconciliation
6. Shadow và paper trade	7 tuần	Live-data simulation, stability tests
7. Small-capital live	4 tuần	1–5% vốn dự kiến
8. Capital ramp	Liên tục	Tăng vốn theo performance gate
Capital ramp

Không đưa toàn bộ vốn vào một lần:

Cấp độ	Vốn sử dụng
Live 0	0% — shadow
Live 1	1%
Live 2	3–5%
Live 3	10–15%
Live 4	25–30%
Production	Chỉ tăng sau đánh giá độc lập

Mỗi lần tăng vốn phải chạy đủ một chu kỳ đánh giá, không tăng vốn chỉ vì vài ngày có lợi nhuận cao.

16. Tiêu chí được phép giao dịch tiền thật

Hệ thống chỉ được go-live khi đạt đồng thời:

Strategy
Có lợi nhuận sau toàn bộ chi phí.
Hiệu quả ở nhiều market regime.
Không phụ thuộc một giai đoạn tăng giá.
Không có lookahead bias.
DSR và PBO đạt ngưỡng nội bộ.
Cost sensitivity vẫn chấp nhận được.
Không sụp đổ khi tăng slippage giả định.
Execution
Không có duplicate order.
Reconciliation hoạt động chính xác.
Partial fill được xử lý đúng.
Restart service không làm mất trạng thái.
Rate-limit và reconnect hoạt động.
Có thể hủy lệnh khẩn cấp.
Risk
Daily loss limit được kiểm thử.
Kill switch được diễn tập.
Không agent nào bypass được Risk Governor.
Có kiểm thử exchange outage và stale data.
Có đối soát PnL độc lập.
Paper/shadow
Chạy liên tục tối thiểu 8–12 tuần.
Không có incident nghiêm trọng chưa xử lý.
PnL live simulation không lệch quá lớn so với backtest.
Slippage model tương đối sát dữ liệu quan sát.
17. Nhân sự cần thiết
Vai trò	Số lượng
Quant/Trading Lead	1
Quant Researcher	1–2
ML Engineer	1
Data Engineer	1
Backend/Execution Engineer	1–2
DevOps/SRE/Security	1
QA/Model Validation	1
Legal/Compliance	Part-time hoặc tư vấn

Một nhóm khoảng 6–8 người có thể xây bản production tốt. Nhóm nhỏ hơn vẫn làm được MVP, nhưng không nên vừa nghiên cứu alpha, vừa làm execution, risk, hạ tầng và kiểm thử bởi một người duy nhất.

18. Phạm vi MVP nên chốt
MVP 1
Một sàn.
Spot BTC/ETH.
Khung thời gian 15 phút–4 giờ.
Ba alpha agents.
Một Regime Agent.
Một Critic Agent.
Meta Allocator.
Risk Governor deterministic.
Execution limit/market.
Shadow trading.
Dashboard PnL và risk.
MVP 2
Perpetual.
Long/short.
Funding và open interest.
Order-book agent.
Dynamic allocation.
Model drift.
Champion–challenger.
Leverage tối đa 2x.
Production nâng cao
Multi-exchange.
Cross-exchange hedge.
Market-neutral.
Automated retraining.
Portfolio optimization.
Independent risk service.
Disaster recovery.
High-availability execution.
Compliance reporting.
19. Lưu ý pháp lý tại Việt Nam

Việt Nam đang triển khai thí điểm thị trường tài sản mã hóa theo Nghị quyết 05/2025/NQ-CP, có hiệu lực từ ngày 9/9/2025 và thời gian thí điểm 5 năm. Bộ Tài chính cho biết thị trường có thể đi vào vận hành trong quý III/2026.

Nghị định 284/2026/NĐ-CP về xử phạt vi phạm hành chính trong lĩnh vực tài sản mã hóa và thị trường tài sản mã hóa được ban hành ngày 16/7/2026, có hiệu lực từ ngày 1/9/2026. Trước khi kết nối tiền thật, dự án cần có workstream riêng để xác định sàn được phép sử dụng, nghĩa vụ thuế, kế toán, lưu trữ giao dịch và các hạn chế liên quan đến nền tảng nước ngoài.

20. Thứ tự ưu tiên triển khai
Data correctness.
Backtest simulator.
Risk Governor.
Execution và reconciliation.
Chiến lược alpha đơn giản nhưng ổn định.
Shadow trading.
Multi-agent debate.
Tự học và tự tối ưu.
Multi-exchange và chiến lược phức tạp.

Sai lầm phổ biến là xây agent phân tích rất thông minh trước, nhưng dữ liệu, mô phỏng fill, quản trị vị thế và risk engine lại sơ sài. Với trading thực tế, Risk Governor và Execution Engine thường quan trọng hơn độ thông minh của LLM.