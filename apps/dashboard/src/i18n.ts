// i18n translations for the Trading Dashboard
// Hệ thống dịch thuật cho Dashboard Giao dịch

export type Lang = 'en' | 'vi';

const translations = {
  // ─── Header ───────────────────────────────────────────────
  appTitle:          { en: 'QuantumAgent Trading Platform', vi: 'Nền Tảng Giao Dịch QuantumAgent' },
  apiOnline:         { en: 'API ONLINE', vi: 'API TRỰC TUYẾN' },
  apiUnavailable:    { en: 'API UNAVAILABLE', vi: 'API KHÔNG KHẢ DỤNG' },

  // ─── AI Advisor panel ──────────────────────────────────────
  advisorTitle:        { en: '🤖 AI Trading Advisor', vi: '🤖 Cố Vấn Giao Dịch AI' },
  advisorSubtitle:     { en: 'Conversational advisor — recommendation only, never places a real trade', vi: 'Cố vấn hội thoại — chỉ đề xuất, không bao giờ tự đặt lệnh thật' },
  advisorNotConfigured: { en: 'Gemini chat is unavailable because GEMINI_API_KEY or GEMINI_MODEL is missing. Public-data deterministic research analysis remains available through Run analysis.', vi: 'Chat Gemini chưa khả dụng vì thiếu GEMINI_API_KEY hoặc GEMINI_MODEL. Phân tích nghiên cứu deterministic từ dữ liệu public vẫn hoạt động qua nút Run analysis.' },
  advisorPlaceholder: { en: 'Ask about market conditions or trade opportunities...', vi: 'Hỏi về tình hình thị trường hoặc cơ hội giao dịch...' },
  advisorSend:       { en: 'Send', vi: 'Gửi' },
  advisorSending:    { en: 'Thinking...', vi: 'Đang xử lý...' },
  advisorEmpty:      { en: 'Ask the advisor what it sees in the market right now.', vi: 'Hỏi cố vấn xem thị trường hiện đang thế nào.' },
  advisorError:      { en: 'The advisor could not process this request.', vi: 'Cố vấn không thể xử lý yêu cầu này.' },
  advisorDisclaimer: { en: 'Research/recommendation only — not financial advice. No trade is ever placed automatically.', vi: 'Chỉ mang tính nghiên cứu/đề xuất — không phải lời khuyên tài chính. Không có lệnh nào được tự động đặt.' },

  // ─── Candlestick chart ─────────────────────────────────────
  chartLoading:            { en: 'Loading chart...', vi: 'Đang tải biểu đồ...' },
  chartNoData:             { en: 'No candle data available.', vi: 'Không có dữ liệu nến.' },
  chartLoadError:          { en: 'Could not load chart data.', vi: 'Không tải được dữ liệu biểu đồ.' },
  chartProjectionLabel:    { en: 'Walk-forward validated model', vi: 'Mô hình đã kiểm định walk-forward' },
  chartProjectionNoModel:  { en: 'No model has been trained for this symbol/timeframe yet.', vi: 'Chưa có mô hình nào được huấn luyện cho cặp/khung thời gian này.' },
  chartProjectionNotApproved: { en: 'A model was trained and evaluated out-of-sample, but did not beat the naive baseline — no line is shown so nothing false is implied.', vi: 'Đã huấn luyện và kiểm định mô hình out-of-sample, nhưng không vượt qua baseline ngây thơ — không hiển thị đường để tránh gây hiểu nhầm.' },
  chartOosMape:            { en: 'OOS MAPE', vi: 'MAPE OOS' },
  chartOosDirAcc:          { en: 'directional accuracy', vi: 'độ chính xác chiều' },
} as const;


export type TranslationKey = keyof typeof translations;

export function useTranslation(lang: Lang) {
  return function t(key: TranslationKey): string {
    return translations[key][lang];
  };
}

export { translations };
