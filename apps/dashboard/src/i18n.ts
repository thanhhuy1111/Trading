// i18n translations for the Trading Dashboard
// Hệ thống dịch thuật cho Dashboard Giao dịch

export type Lang = 'en' | 'vi';

const translations = {
  // ─── Header ───────────────────────────────────────────────
  appTitle:          { en: 'QuantumAgent Trading Platform', vi: 'Nền Tảng Giao Dịch QuantumAgent' },
  appSubtitle:       { en: 'Production-Grade Multi-Agent Cryptocurrency System', vi: 'Hệ Thống Đa Agent Tiền Điện Tử Cấp Sản Xuất' },
  apiOnline:         { en: 'API ONLINE', vi: 'API TRỰC TUYẾN' },
  apiUnavailable:    { en: 'API UNAVAILABLE', vi: 'API KHÔNG KHẢ DỤNG' },
  liveTrading:       { en: 'LIVE TRADING:', vi: 'GIAO DỊCH THẬT:' },
  disabled:          { en: 'DISABLED', vi: 'TẮT' },
  mode:              { en: 'MODE:', vi: 'CHẾ ĐỘ:' },
  startSystem:       { en: 'START SYSTEM', vi: 'KHỞI ĐỘNG' },
  pause:             { en: 'PAUSE', vi: 'TẠM DỪNG' },
  softStop:          { en: 'SOFT STOP', vi: 'DỪNG MỀM' },
  killSwitch:        { en: 'KILL SWITCH', vi: 'DỪNG KHẨN CẤP' },

  // ─── Kill Switch Modal ─────────────────────────────────────
  killSwitchTitle:   { en: 'Confirm Emergency Kill Switch (HARD STOP)', vi: 'Xác Nhận Dừng Khẩn Cấp (HARD STOP)' },
  killSwitchBody:    { en: 'Are you sure you want to trigger a HARD STOP? This will cancel all open orders, halt system trading immediately, and prevent any new orders.', vi: 'Bạn có chắc muốn kích hoạt HARD STOP? Hành động này sẽ hủy tất cả lệnh đang mở, dừng hệ thống ngay lập tức và ngăn mọi lệnh mới.' },
  cancel:            { en: 'Cancel', vi: 'Hủy' },
  confirmHardStop:   { en: 'CONFIRM HARD STOP', vi: 'XÁC NHẬN HARD STOP' },

  // ─── Sidebar ───────────────────────────────────────────────
  navPnl:            { en: 'P&L Monitor', vi: 'Theo Dõi Lãi/Lỗ' },
  navSecurity:       { en: 'Security & Supply Chain', vi: 'Bảo Mật & Chuỗi Cung Ứng' },
  navObservability:  { en: 'Observability & Metrics', vi: 'Giám Sát & Chỉ Số' },
  navLineage:        { en: 'Pipeline Lineage & Tracing', vi: 'Truy Vết Pipeline' },
  navPaper:          { en: 'Real-Time Paper Trading', vi: 'Giao Dịch Giả Thời Gian Thực' },
  navMarketData:     { en: 'Market Data', vi: 'Dữ Liệu Thị Trường' },
  navDataQuality:    { en: 'Data Quality & Guardian', vi: 'Chất Lượng Dữ Liệu & Guardian' },
  navFeatures:       { en: 'Feature Explorer', vi: 'Khám Phá Tính Năng' },
  navSignals:        { en: 'Signal Explorer', vi: 'Khám Phá Tín Hiệu' },
  navCritic:         { en: 'Critic Agent Scrutiny', vi: 'Critic Agent Kiểm Duyệt' },
  navTradeIntents:   { en: 'TradeIntent Explorer', vi: 'Khám Phá Lệnh Dự Kiến' },
  navRiskGovernor:   { en: 'Risk Governor & Orders', vi: 'Quản Lý Rủi Ro & Lệnh' },
  navExecution:      { en: 'Execution Engine & Simulator', vi: 'Máy Thực Thi & Mô Phỏng' },
  navPositions:      { en: 'Positions & Portfolio Ledger', vi: 'Vị Thế & Sổ Cái Portfolio' },
  navConfig:         { en: 'Configuration', vi: 'Cấu Hình' },
  navAgents:         { en: 'Intelligence Agents', vi: 'Agent Thông Minh' },
  navOrders:         { en: 'Order Execution', vi: 'Thực Thi Lệnh' },
  navRisk:           { en: 'Risk Governor', vi: 'Quản Lý Rủi Ro' },
  navBacktest:       { en: 'Backtest Engine', vi: 'Máy Backtest' },
  navIncidents:      { en: 'Incidents & Logs', vi: 'Sự Cố & Nhật Ký' },
  navAdvisor:        { en: 'AI Trading Advisor', vi: 'Cố Vấn AI' },
  navRecommendations: { en: 'Trade Recommendations', vi: 'Đề Xuất Giao Dịch' },
  mock:              { en: 'Mock', vi: 'Mô Phỏng' },

  // ─── AI Advisor tab ───────────────────────────────────────
  advisorTitle:        { en: '🤖 AI Trading Advisor', vi: '🤖 Cố Vấn Giao Dịch AI' },
  advisorSubtitle:     { en: 'Conversational advisor — recommendation only, never places a real trade', vi: 'Cố vấn hội thoại — chỉ đề xuất, không bao giờ tự đặt lệnh thật' },
  advisorNotConfigured: { en: 'AI Advisor is not configured on this server (GEMINI_API_KEY missing). The rest of the system — recommendations, risk, execution — works independently of this.', vi: 'Cố Vấn AI chưa được cấu hình trên server này (thiếu GEMINI_API_KEY). Phần còn lại của hệ thống — đề xuất, quản lý rủi ro, thực thi — hoạt động độc lập với tính năng này.' },
  advisorPlaceholder: { en: 'Ask about market conditions or trade opportunities...', vi: 'Hỏi về tình hình thị trường hoặc cơ hội giao dịch...' },
  advisorSend:       { en: 'Send', vi: 'Gửi' },
  advisorSending:    { en: 'Thinking...', vi: 'Đang xử lý...' },
  advisorEmpty:      { en: 'Ask the advisor what it sees in the market right now.', vi: 'Hỏi cố vấn xem thị trường hiện đang thế nào.' },
  advisorError:      { en: 'The advisor could not process this request.', vi: 'Cố vấn không thể xử lý yêu cầu này.' },
  advisorDisclaimer: { en: 'Research/recommendation only — not financial advice. No trade is ever placed automatically.', vi: 'Chỉ mang tính nghiên cứu/đề xuất — không phải lời khuyên tài chính. Không có lệnh nào được tự động đặt.' },

  // ─── Recommendations tab ──────────────────────────────────
  recommendationsTitle:    { en: '🎯 Trade Recommendation Scanner', vi: '🎯 Quét Đề Xuất Giao Dịch' },
  recommendationsSubtitle: { en: 'Runs the real agent -> critic -> consensus -> evidence -> risk pipeline — never a fabricated proposal', vi: 'Chạy pipeline thật: agent -> critic -> consensus -> evidence -> risk — không bao giờ tạo đề xuất giả' },
  readinessTitle:    { en: 'System Readiness', vi: 'Trạng Thái Sẵn Sàng' },
  scanSymbolsLabel:  { en: 'Symbols (comma-separated)', vi: 'Cặp Tiền (phân tách bằng dấu phẩy)' },
  scanTimeframeLabel: { en: 'Timeframe', vi: 'Khung Thời Gian' },
  scanBtn:           { en: 'Scan for Opportunities', vi: 'Quét Cơ Hội' },
  scanning:          { en: 'Scanning...', vi: 'Đang quét...' },
  scanError:         { en: 'Scan failed.', vi: 'Quét thất bại.' },
  noProposals:       { en: 'No trade proposal met the bar this scan.', vi: 'Không có đề xuất nào đạt điều kiện trong lần quét này.' },
  proposalsFound:    { en: 'proposal(s) found', vi: 'đề xuất được tìm thấy' },
  reasonCodes:       { en: 'Reason codes', vi: 'Mã lý do' },
  colDirection:      { en: 'Direction', vi: 'Chiều' },
  colEntry:          { en: 'Entry Ref.', vi: 'Giá Vào Tham Chiếu' },
  colTakeProfit:     { en: 'Take Profit', vi: 'Chốt Lời' },
  colRiskReward:     { en: 'Risk/Reward', vi: 'Tỷ Lệ R/R' },
  colProbability:    { en: 'Calibrated Prob.', vi: 'Xác Suất Đã Hiệu Chỉnh' },
  colNetReturn:      { en: 'Expected Net Return', vi: 'Lợi Nhuận Ròng Kỳ Vọng' },
  colEvidenceStatus: { en: 'Evidence Status', vi: 'Trạng Thái Bằng Chứng' },
  colResultState:    { en: 'Result State', vi: 'Trạng Thái Kết Quả' },
  colApprovedRisk:   { en: 'Approved Risk', vi: 'Rủi Ro Đã Duyệt' },
  researchOnly:      { en: 'RESEARCH ONLY — not actionable for real capital', vi: 'CHỈ NGHIÊN CỨU — chưa dùng được cho vốn thật' },

  // ─── P&L Monitor ──────────────────────────────────────────
  pnlTitle:          { en: '📊 Trading P&L Monitor', vi: '📊 Theo Dõi Lãi / Lỗ Giao Dịch' },
  pnlSubtitle:       { en: 'Live positions, fills & portfolio performance — Paper Trading Mode', vi: 'Vị thế, lệnh khớp & hiệu suất portfolio — Chế Độ Giao Dịch Giả' },
  livePrices:        { en: 'LIVE PRICES', vi: 'GIÁ THỰC' },
  paperTrading:      { en: 'PAPER TRADING', vi: 'GIAO DỊCH GIẢ' },
  apiOffline:        { en: 'API OFFLINE', vi: 'API NGOẠI TUYẾN' },
  binanceFeed:       { en: 'Binance Public WebSocket', vi: 'WebSocket Công Khai Binance' },

  // Portfolio KPIs
  portfolioNav:      { en: 'Portfolio NAV', vi: 'Tổng Tài Sản (NAV)' },
  paperAccount:      { en: 'Paper Account', vi: 'Tài Khoản Giả' },
  unrealizedPnl:     { en: 'Unrealized P&L', vi: 'Lãi/Lỗ Chưa Chốt' },
  openPositions:     { en: 'open positions', vi: 'vị thế đang mở' },
  openPosition:      { en: 'open position', vi: 'vị thế đang mở' },
  realizedPnlToday:  { en: 'Realized P&L Today', vi: 'Lãi/Lỗ Đã Chốt Hôm Nay' },
  fillsToday:        { en: 'fills today', vi: 'lệnh khớp hôm nay' },
  exposureCash:      { en: 'Exposure / Cash', vi: 'Đang Đầu Tư / Tiền Mặt' },
  cash:              { en: 'Cash:', vi: 'Tiền mặt:' },

  // Positions table
  openPositionsTitle: { en: 'Open Positions', vi: 'Vị Thế Đang Mở' },
  noPositions:       { en: 'No open positions — system is awaiting trade signals', vi: 'Không có vị thế nào — hệ thống đang chờ tín hiệu giao dịch' },
  colSymbol:         { en: 'Symbol', vi: 'Cặp Tiền' },
  colSide:           { en: 'Side', vi: 'Chiều' },
  colQty:            { en: 'Qty', vi: 'Số Lượng' },
  colAvgEntry:       { en: 'Avg Entry', vi: 'Giá Vào Trung Bình' },
  colMarketPrice:    { en: 'Market Price', vi: 'Giá Thị Trường' },
  colNotional:       { en: 'Notional', vi: 'Giá Trị' },
  colUnrealizedPnl:  { en: 'Unrealized P&L', vi: 'Lãi/Lỗ Chưa Chốt' },
  colReturn:         { en: 'Return %', vi: 'Lợi Nhuận %' },
  colStopPrice:      { en: 'Stop Price', vi: 'Giá Cắt Lỗ' },
  colStatus:         { en: 'Status', vi: 'Trạng Thái' },
  portfolioTotals:   { en: 'Portfolio Totals', vi: 'Tổng Portfolio' },

  // Fills table
  recentFills:       { en: 'Recent Fills', vi: 'Lệnh Khớp Gần Đây' },
  totalFills:        { en: 'total fills', vi: 'lệnh khớp' },
  colFillId:         { en: 'Fill ID', vi: 'Mã Lệnh' },
  colFee:            { en: 'Fee', vi: 'Phí' },
  colRealizedPnl:    { en: 'Realized P&L', vi: 'Lãi/Lỗ Đã Chốt' },
  colTime:           { en: 'Time', vi: 'Thời Gian' },

  // Status bar
  riskEngine:        { en: 'Risk Engine:', vi: 'Máy Quản Lý Rủi Ro:' },
  normal:            { en: 'NORMAL', vi: 'BÌNH THƯỜNG' },
  guardian:          { en: 'Guardian:', vi: 'Guardian:' },
  healthy:           { en: 'HEALTHY', vi: 'KHỎE MẠNH' },
  feed:              { en: 'Feed: Binance Public WebSocket (BTC/USDT, ETH/USDT)', vi: 'Nguồn: WebSocket Binance (BTC/USDT, ETH/USDT)' },

  // ─── Market Data tab ──────────────────────────────────────
  marketDataTitle:   { en: 'Market Data Streams', vi: 'Luồng Dữ Liệu Thị Trường' },
  marketDataSub:     { en: 'Public Binance Market Feed (Read-Only)', vi: 'Dữ Liệu Binance Công Khai (Chỉ Đọc)' },
  publicApiOnly:     { en: 'Public API Only', vi: 'Chỉ API Công Khai' },
  tradingDisabled:   { en: 'Trading Disabled', vi: 'Giao Dịch Đã Tắt' },
  registeredSymbols: { en: 'Registered Canonical Symbols', vi: 'Các Cặp Tiền Đã Đăng Ký' },
  loadingSymbols:    { en: 'Loading symbols...', vi: 'Đang tải cặp tiền...' },

  // Candlestick chart
  chartTitle:              { en: 'Price Chart', vi: 'Biểu Đồ Giá' },
  chartSymbolLabel:        { en: 'Symbol', vi: 'Cặp Tiền' },
  chartTimeframeLabel:     { en: 'Timeframe', vi: 'Khung Thời Gian' },
  chartLoading:            { en: 'Loading chart...', vi: 'Đang tải biểu đồ...' },
  chartNoData:             { en: 'No candle data available.', vi: 'Không có dữ liệu nến.' },
  chartLoadError:          { en: 'Could not load chart data.', vi: 'Không tải được dữ liệu biểu đồ.' },
  chartProjectionLabel:    { en: 'Walk-forward validated model', vi: 'Mô hình đã kiểm định walk-forward' },
  chartProjectionNoModel:  { en: 'No model has been trained for this symbol/timeframe yet.', vi: 'Chưa có mô hình nào được huấn luyện cho cặp/khung thời gian này.' },
  chartProjectionNotApproved: { en: 'A model was trained and evaluated out-of-sample, but did not beat the naive baseline — no line is shown so nothing false is implied.', vi: 'Đã huấn luyện và kiểm định mô hình out-of-sample, nhưng không vượt qua baseline ngây thơ — không hiển thị đường để tránh gây hiểu nhầm.' },
  chartOosMape:            { en: 'OOS MAPE', vi: 'MAPE OOS' },
  chartOosDirAcc:          { en: 'directional accuracy', vi: 'độ chính xác chiều' },

  // ─── Config tab ───────────────────────────────────────────
  configTitle:       { en: 'Dynamic Configuration Manager', vi: 'Quản Lý Cấu Hình Động' },
  versionedAudited:  { en: 'Versioned & Audited', vi: 'Có Phiên Bản & Kiểm Toán' },
  colNamespace:      { en: 'Namespace', vi: 'Nhóm Cấu Hình' },
  colName:           { en: 'Name', vi: 'Tên' },
  colVersion:        { en: 'Version', vi: 'Phiên Bản' },
  colChecksum:       { en: 'SHA-256 Checksum', vi: 'Mã Kiểm Tra SHA-256' },
  noConfig:          { en: 'No configuration sets registered yet.', vi: 'Chưa có bộ cấu hình nào được đăng ký.' },

  // ─── Data Quality tab ─────────────────────────────────────
  dataQualityTitle:  { en: 'Data Guardian & Quality Status', vi: 'Trạng Thái Data Guardian & Chất Lượng' },
  dataQualitySub:    { en: 'Freshness, Completeness, Validity, and Anomaly Audit Engine', vi: 'Độ Tươi Mới, Đầy Đủ, Hợp Lệ & Phát Hiện Bất Thường' },
  resyncBtn:         { en: 'RESYNC BTC/USDT', vi: 'ĐỒNG BỘ LẠI BTC/USDT' },

  // ─── Positions tab ────────────────────────────────────────
  positionsTitle:    { en: 'Positions & Portfolio Ledger', vi: 'Vị Thế & Sổ Cái Portfolio' },
  totalCashBalance:  { en: 'Total Cash Balance', vi: 'Số Dư Tiền Mặt' },
  assetMarketValue:  { en: 'Asset Market Value', vi: 'Giá Trị Tài Sản Thị Trường' },
  portfolioNAV:      { en: 'Portfolio NAV', vi: 'Tổng Tài Sản Ròng' },
  peakDrawdown:      { en: 'Peak / Drawdown %', vi: 'Đỉnh / Drawdown %' },

  // ─── Pending Orders ───────────────────────────────────────
  pendingOrdersTitle: { en: 'Pending Orders', vi: 'Lệnh Chờ Khớp' },
  pendingOrdersSub:   { en: 'Open orders waiting to be matched by the exchange', vi: 'Các lệnh đang chờ khớp tại sàn giao dịch' },
  noPendingOrders:    { en: 'No pending orders — all orders have been filled or cancelled', vi: 'Không có lệnh chờ khớp — tất cả lệnh đã được khớp hoặc hủy' },
  colOrderId:         { en: 'Order ID', vi: 'Mã Lệnh' },
  colOrderType:       { en: 'Type', vi: 'Loại Lệnh' },
  colLimitPrice:      { en: 'Limit Price', vi: 'Giá Đặt' },
  colStopTrigger:     { en: 'Stop Trigger', vi: 'Giá Kích Hoạt' },
  colFilled:          { en: 'Filled / Total', vi: 'Đã Khớp / Tổng' },
  colTIF:             { en: 'TIF', vi: 'Hiệu Lực' },
  colAge:             { en: 'Age', vi: 'Thời Gian Chờ' },
  colAction:          { en: 'Action', vi: 'Thao Tác' },
  cancelOrder:        { en: 'Cancel', vi: 'Hủy' },
  statusPending:      { en: 'PENDING', vi: 'CHỜ KHỚP' },
  statusPartial:      { en: 'PARTIAL', vi: 'KHỚP MỘT PHẦN' },
  statusOpen:         { en: 'OPEN', vi: 'ĐANG MỞ' },
  distToLimit:        { en: 'Dist. to limit', vi: 'Cách giá đặt' },
} as const;


export type TranslationKey = keyof typeof translations;

export function useTranslation(lang: Lang) {
  return function t(key: TranslationKey): string {
    return translations[key][lang];
  };
}

export { translations };
