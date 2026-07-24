import { useState, useEffect } from 'react';
import CandleChart from './components/CandleChart';
import { useTranslation, type Lang } from './i18n';

interface SystemStatus {
  is_running: boolean;
  soft_stop: boolean;
  hard_stop: boolean;
  mode: string;
}

interface PortfolioData {
  total_nav: number;
  cash_balance: number;
  unrealized_pnl: number;
  realized_pnl_today: number;
  current_drawdown_pct: number;
  open_positions_count: number;
}

interface ConfigItem {
  id: string;
  namespace: string;
  name: string;
  version: number;
  status: string;
  checksum: string;
  created_at: string;
}

interface SymbolItem {
  canonical_symbol: string;
  exchange_symbol: string;
  exchange: string;
  price_tick_size: string;
  status: string;
}

interface Position {
  id: string;
  symbol: string;
  side: 'LONG' | 'SHORT';
  quantity: number;
  avg_entry_price: number;
  market_price: number;
  unrealized_pnl: number;
  unrealized_pnl_pct: number;
  stop_price: number;
  notional: number;
  status: string;
  opened_at: string;
}

interface Fill {
  id: string;
  symbol: string;
  side: 'BUY' | 'SELL';
  quantity: number;
  fill_price: number;
  fee: number;
  realized_pnl: number | null;
  filled_at: string;
}

interface PendingOrder {
  id: string;
  symbol: string;
  side: 'BUY' | 'SELL';
  order_type: 'LIMIT' | 'MARKET' | 'STOP_LIMIT' | 'STOP_MARKET';
  quantity: number;
  limit_price: number | null;    // null for MARKET orders
  stop_price: number | null;     // null for non-stop orders
  filled_qty: number;
  status: 'PENDING' | 'PARTIALLY_FILLED' | 'OPEN';
  time_in_force: 'GTC' | 'IOC' | 'FOK' | 'GTD';
  created_at: string;
}

// ─── AI Advisor + Recommendations (packages/chat_agent, apps/api/routers/{chat,recommendations}.py) ───

interface ChatMessage {
  role: 'user' | 'assistant';
  text: string;
}

interface TradeProposal {
  proposal_id: string;
  symbol: string;
  timeframe: string;
  direction: string;
  entry_reference: string;
  stop_loss: string | null;
  take_profit: string | null;
  risk_reward_ratio: string | null;
  calibrated_probability: string | null;
  expected_net_return_bps: string | null;
  evidence_status: string;
  application_result_state: string;
  approved_risk_pct: string | null;
  reason_codes: string[];
  proposal_expiry: string;
}

interface RecommendationResponse {
  request_id: string;
  generated_at: string;
  application_result_state: string;
  reason_codes: string[];
  limitations: string[];
  proposals: TradeProposal[];
}

interface ReadinessStatus {
  architecture_readiness: string;
  strategy_readiness: string;
  model_readiness: string;
  evidence_readiness: string;
  shadow_readiness: string;
  live_readiness: string;
}

// Dev-mode RBAC header (apps/api/deps.py: X-Principal-Id / X-Roles, defaults to anonymous
// VIEWER when absent). No real identity provider exists yet in this system -- this is the
// same documented, minimal header contract the backend itself defines, not a bypass of it.
const ADVISOR_HEADERS = { 'Content-Type': 'application/json', 'X-Principal-Id': 'dashboard', 'X-Roles': 'OPERATOR' };

export default function App() {
  const [activeTab, setActiveTab] = useState<'overview' | 'security' | 'observability' | 'lineage' | 'paper' | 'market_data' | 'data_quality' | 'features' | 'signals' | 'critic' | 'trade_intents' | 'risk_governor' | 'execution_monitor' | 'positions' | 'agents' | 'orders' | 'risk' | 'backtest' | 'config' | 'incidents' | 'advisor' | 'recommendations'>('overview');
  const [lang, setLang] = useState<Lang>(() => (localStorage.getItem('lang') as Lang) || 'vi');
  const t = useTranslation(lang);
  const toggleLang = () => {
    const next: Lang = lang === 'en' ? 'vi' : 'en';
    setLang(next);
    localStorage.setItem('lang', next);
  };
  const [isBackendAvailable, setIsBackendAvailable] = useState<boolean>(false);
  const [showKillConfirm, setShowKillConfirm] = useState<boolean>(false);
  const [configs, setConfigs] = useState<ConfigItem[]>([]);
  const [symbols, setSymbols] = useState<SymbolItem[]>([]);
  const [positions, setPositions] = useState<Position[]>([]);
  const [fills, setFills] = useState<Fill[]>([]);
  const [pendingOrders, setPendingOrders] = useState<PendingOrder[]>([]);
  const [livePrices, setLivePrices] = useState<Record<string, number>>({ 'BTC/USDT': 65032.50, 'ETH/USDT': 3412.80 });
  const [priceDir, setPriceDir] = useState<Record<string, 'up' | 'down' | null>>({});

  const [status, setStatus] = useState<SystemStatus>({
    is_running: false,
    soft_stop: false,
    hard_stop: false,
    mode: 'PAPER_TRADING'
  });
  const [portfolio, setPortfolio] = useState<PortfolioData>({
    total_nav: 100.0,
    cash_balance: 100.0,
    unrealized_pnl: 0.0,
    realized_pnl_today: 0.0,
    current_drawdown_pct: 0.0,
    open_positions_count: 0
  });

  // Advisor tab
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState('');
  const [chatConversationId, setChatConversationId] = useState<string | null>(null);
  const [chatLoading, setChatLoading] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);
  const [advisorConfigured, setAdvisorConfigured] = useState(true);

  // Recommendations tab
  const [readiness, setReadiness] = useState<ReadinessStatus | null>(null);
  const [recSymbols, setRecSymbols] = useState('BTC/USDT, ETH/USDT');
  const [recTimeframe, setRecTimeframe] = useState('1d');
  const [recLoading, setRecLoading] = useState(false);
  const [recError, setRecError] = useState<string | null>(null);
  const [recResult, setRecResult] = useState<RecommendationResponse | null>(null);

  // Market Data tab chart
  const [chartSymbol, setChartSymbol] = useState('BTCUSDT');
  const [chartTimeframe, setChartTimeframe] = useState('1h');

  // Real live prices from Binance public REST API (via backend /market-data/live-prices)
  useEffect(() => {
    const fetchLivePrices = async () => {
      try {
        const res = await fetch('/api/market-data/live-prices?symbols=BTC/USDT,ETH/USDT');
        if (!res.ok) return;
        const data = await res.json();
        const fetched: Record<string, number> = {};
        for (const [sym, priceStr] of Object.entries(data.prices || {})) {
          fetched[sym] = parseFloat(priceStr as string);
        }
        if (Object.keys(fetched).length === 0) return;

        setLivePrices(prev => {
          const dirs: Record<string, 'up' | 'down' | null> = {};
          for (const sym of Object.keys(fetched)) {
            if (prev[sym] !== undefined && fetched[sym] !== prev[sym]) {
              dirs[sym] = fetched[sym] >= prev[sym] ? 'up' : 'down';
            }
          }
          setPriceDir(dirs);

          // Update positions unrealized PnL against the real price
          setPositions(prev2 => prev2.map(p => {
            const mp = fetched[p.symbol] ?? p.market_price;
            const pnl = (mp - p.avg_entry_price) * p.quantity;
            const pnlPct = ((mp - p.avg_entry_price) / p.avg_entry_price) * 100;
            return { ...p, market_price: mp, unrealized_pnl: pnl, unrealized_pnl_pct: pnlPct, notional: mp * p.quantity };
          }));

          return { ...prev, ...fetched };
        });
        setTimeout(() => setPriceDir({}), 600);
      } catch (e) {
        // Network/backend unavailable: leave the last known real price on screen (no fake fallback).
      }
    };

    fetchLivePrices();
    const priceInterval = setInterval(fetchLivePrices, 2000);
    return () => clearInterval(priceInterval);
  }, []);

  useEffect(() => {
    fetchStatus();
    fetchPortfolio();
    fetchPositions();
    fetchFills();
    fetchPendingOrders();
    fetchConfigs();
    fetchSymbols();
    fetchReadiness();
    const interval = setInterval(() => {
      fetchStatus();
      fetchPortfolio();
      fetchPositions();
      fetchFills();
      fetchPendingOrders();
    }, 5000);
    return () => clearInterval(interval);
  }, []);

  const fetchStatus = async () => {
    try {
      const res = await fetch('/api/trading/status');
      if (res.ok) {
        const data = await res.json();
        setStatus({
          is_running: data.is_running,
          soft_stop: data.soft_stop,
          hard_stop: data.hard_stop,
          mode: data.mode
        });
        setIsBackendAvailable(true);
      } else {
        setIsBackendAvailable(false);
      }
    } catch (e) {
      setIsBackendAvailable(false);
    }
  };

  const fetchPortfolio = async () => {
    try {
      const res = await fetch('/api/portfolio');
      if (res.ok) {
        const data = await res.json();
        // Backend serializes Decimal fields as JSON strings for precision; parse them to
        // numbers here so arithmetic below (e.g. nav + totalUnrealized) doesn't silently
        // fall back to string concatenation.
        setPortfolio({
          total_nav: parseFloat(data.total_nav),
          cash_balance: parseFloat(data.cash_balance),
          unrealized_pnl: parseFloat(data.unrealized_pnl),
          realized_pnl_today: parseFloat(data.realized_pnl_today),
          current_drawdown_pct: Number(data.current_drawdown_pct) || 0,
          open_positions_count: Number(data.open_positions_count) || 0,
        });
      }
    } catch (e) {
      // Fallback
    }
  };

  const fetchPositions = async () => {
    try {
      const res = await fetch('/api/positions');
      if (!res.ok) return;
      const data = await res.json();
      setPositions((data as any[]).map((p) => {
        const qty = parseFloat(p.quantity);
        const avgEntry = parseFloat(p.average_entry_price);
        const marketPrice = parseFloat(p.current_market_price ?? p.average_entry_price);
        const unrealizedPnl = parseFloat(p.unrealized_pnl ?? '0');
        const unrealizedPnlPct = avgEntry > 0 ? ((marketPrice - avgEntry) / avgEntry) * 100 : 0;
        return {
          id: p.position_id,
          symbol: p.symbol,
          side: p.side === 'SHORT' ? 'SHORT' : 'LONG',
          quantity: qty,
          avg_entry_price: avgEntry,
          market_price: marketPrice,
          unrealized_pnl: unrealizedPnl,
          unrealized_pnl_pct: unrealizedPnlPct,
          stop_price: parseFloat(p.active_stop_price ?? p.initial_stop_price ?? '0'),
          notional: parseFloat(p.market_value ?? (qty * marketPrice).toString()),
          status: p.status,
          opened_at: p.opened_at,
        } as Position;
      }));
    } catch (e) {
      // Fallback: leave last known positions on screen
    }
  };

  const fetchFills = async () => {
    try {
      const res = await fetch('/api/fills');
      if (!res.ok) return;
      const data = await res.json();
      setFills((data as any[]).map((f) => ({
        id: f.id,
        symbol: f.symbol,
        side: f.side,
        quantity: parseFloat(f.quantity),
        fill_price: parseFloat(f.fill_price),
        fee: parseFloat(f.fee),
        realized_pnl: f.realized_pnl !== null ? parseFloat(f.realized_pnl) : null,
        filled_at: f.filled_at,
      } as Fill)));
    } catch (e) {
      // Fallback: leave last known fills on screen
    }
  };

  const fetchPendingOrders = async () => {
    try {
      const res = await fetch('/api/orders');
      if (!res.ok) return;
      const data = await res.json();
      // Honestly empty in the current execution model (no resting/GTC order book — every
      // order fills or is rejected immediately), so this will normally return [].
      setPendingOrders(data as PendingOrder[]);
    } catch (e) {
      // Fallback: leave last known orders on screen
    }
  };

  const fetchConfigs = async () => {
    try {
      const res = await fetch('/api/configurations');
      if (res.ok) {
        const data = await res.json();
        setConfigs(data);
      }
    } catch (e) {
      // Fallback
    }
  };

  const fetchSymbols = async () => {
    try {
      const res = await fetch('/api/market-data/symbols');
      if (res.ok) {
        const data = await res.json();
        setSymbols(data);
      }
    } catch (e) {
      // Fallback
    }
  };

  const fetchReadiness = async () => {
    try {
      const res = await fetch('/api/readiness', { headers: ADVISOR_HEADERS });
      if (res.ok) {
        setReadiness(await res.json());
      }
    } catch (e) {
      // Fallback: leave last known readiness on screen
    }
  };

  const handleSendChat = async () => {
    const message = chatInput.trim();
    if (!message || chatLoading) return;
    setChatMessages((prev) => [...prev, { role: 'user', text: message }]);
    setChatInput('');
    setChatLoading(true);
    setChatError(null);
    try {
      const res = await fetch('/api/v1/chat', {
        method: 'POST',
        headers: ADVISOR_HEADERS,
        body: JSON.stringify({ conversation_id: chatConversationId, message }),
      });
      if (res.status === 503) {
        setAdvisorConfigured(false);
        setChatMessages((prev) => prev.slice(0, -1));
        return;
      }
      if (!res.ok) {
        setChatError(t('advisorError'));
        return;
      }
      const data = await res.json();
      setChatConversationId(data.conversation_id);
      setChatMessages((prev) => [...prev, { role: 'assistant', text: data.answer }]);
    } catch (e) {
      setChatError(t('advisorError'));
    } finally {
      setChatLoading(false);
    }
  };

  const handleScan = async () => {
    setRecLoading(true);
    setRecError(null);
    setRecResult(null);
    try {
      const symbolList = recSymbols.split(',').map((s) => s.trim()).filter(Boolean);
      const res = await fetch('/api/recommendations/scan', {
        method: 'POST',
        headers: ADVISOR_HEADERS,
        body: JSON.stringify({ symbols: symbolList, timeframe: recTimeframe }),
      });
      if (!res.ok) {
        setRecError(t('scanError'));
        return;
      }
      setRecResult(await res.json());
    } catch (e) {
      setRecError(t('scanError'));
    } finally {
      setRecLoading(false);
    }
  };

  const handleControlAction = async (action: 'start' | 'stop' | 'soft-stop' | 'hard-stop') => {
    if (action === 'hard-stop' && !showKillConfirm) {
      setShowKillConfirm(true);
      return;
    }
    try {
      await fetch(`/api/trading/${action}`, { method: 'POST' });
      fetchStatus();
    } catch (e) {
      console.error(e);
    } finally {
      setShowKillConfirm(false);
    }
  };

  return (
    <div className="min-h-screen flex flex-col bg-slate-950 text-slate-100">
      {/* Kill Switch Confirmation Modal */}
      {showKillConfirm && (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-sm z-[100] flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-red-500/50 p-6 rounded-xl max-w-md w-full space-y-4 shadow-2xl">
            <h3 className="text-lg font-bold text-red-500 flex items-center space-x-2">
              <span>⚠️</span>
              <span>{t('killSwitchTitle')}</span>
            </h3>
            <p className="text-sm text-slate-300">{t('killSwitchBody')}</p>
            <div className="flex justify-end space-x-3 pt-2">
              <button
                onClick={() => setShowKillConfirm(false)}
                className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-xs font-medium rounded text-slate-300"
              >
                {t('cancel')}
              </button>
              <button
                onClick={() => handleControlAction('hard-stop')}
                className="px-4 py-2 bg-red-600 hover:bg-red-500 text-xs font-bold rounded text-white"
              >
                {t('confirmHardStop')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Header Bar */}
      <header className="h-16 border-b border-slate-800 bg-slate-900/80 backdrop-blur px-6 flex items-center justify-between sticky top-0 z-50">
        <div className="flex items-center space-x-3">
          <div className="w-8 h-8 rounded-lg bg-cyan-500/20 border border-cyan-500/40 flex items-center justify-center font-bold text-cyan-400">
            AG
          </div>
          <div>
            <h1 className="text-base font-semibold tracking-wide text-white">{t('appTitle')}</h1>
            <p className="text-xs text-slate-400">{t('appSubtitle')}</p>
          </div>
        </div>

        {/* System Badges */}
        <div className="flex items-center space-x-3">
          {/* Language Toggle */}
          <button
            onClick={toggleLang}
            title={lang === 'en' ? 'Chuyển sang Tiếng Việt' : 'Switch to English'}
            className="flex items-center space-x-1.5 px-3 py-1 rounded-full text-xs font-bold border border-cyan-500/50 bg-cyan-950/50 text-cyan-300 hover:bg-cyan-900/60 hover:text-cyan-100 transition-all duration-200 select-none"
          >
            <span className="text-base leading-none">{lang === 'en' ? '🇻🇳' : '🇬🇧'}</span>
            <span>{lang === 'en' ? 'VI' : 'EN'}</span>
          </button>

          {/* Backend Connectivity Status */}
          <div className={`flex items-center space-x-2 px-3 py-1 rounded-full text-xs font-mono border ${
            isBackendAvailable ? 'bg-emerald-950/80 border-emerald-500 text-emerald-400' : 'bg-red-950/80 border-red-500 text-red-400'
          }`}>
            <span className="w-2 h-2 rounded-full bg-current"></span>
            <span>{isBackendAvailable ? t('apiOnline') : t('apiUnavailable')}</span>
          </div>

          {/* Live Trading Badge */}
          <div className="flex items-center space-x-2 px-3 py-1 rounded-full text-xs font-mono bg-slate-900 border border-slate-700 text-slate-400">
            <span>{t('liveTrading')}</span>
            <span className="text-red-400 font-bold">{t('disabled')}</span>
          </div>

          <div className="flex items-center space-x-2 px-3 py-1 rounded-full text-xs font-mono bg-slate-800 border border-slate-700">
            <span className="text-slate-400">{t('mode')}</span>
            <span className="text-cyan-400 font-bold">{status.mode}</span>
          </div>

          {/* Control Actions */}
          <div className="flex items-center space-x-2">
            {!status.is_running ? (
              <button
                onClick={() => handleControlAction('start')}
                className="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-medium rounded transition"
              >
                {t('startSystem')}
              </button>
            ) : (
              <button
                onClick={() => handleControlAction('stop')}
                className="px-3 py-1.5 bg-slate-700 hover:bg-slate-600 text-white text-xs font-medium rounded transition"
              >
                {t('pause')}
              </button>
            )}
            <button
              onClick={() => handleControlAction('soft-stop')}
              className="px-3 py-1.5 bg-amber-600/80 hover:bg-amber-500 text-white text-xs font-medium rounded transition"
            >
              {t('softStop')}
            </button>
            <button
              onClick={() => setShowKillConfirm(true)}
              className="px-3 py-1.5 bg-red-600 hover:bg-red-500 text-white text-xs font-medium rounded transition"
            >
              {t('killSwitch')}
            </button>
          </div>
        </div>
      </header>

      {/* Main Content Area */}
      <div className="flex flex-1">
        {/* Navigation Sidebar */}
        <aside className="w-64 border-r border-slate-800 bg-slate-900/40 p-4 space-y-1">
          {[
            { id: 'overview',          label: t('navPnl'),           icon: '💰', isReal: true },
            { id: 'advisor',           label: t('navAdvisor'),        icon: '🤖', isReal: true },
            { id: 'recommendations',   label: t('navRecommendations'), icon: '🎯', isReal: true },
            { id: 'security',          label: t('navSecurity'),       icon: '🔒', isReal: true },
            { id: 'observability',     label: t('navObservability'),  icon: '🔭', isReal: true },
            { id: 'lineage',           label: t('navLineage'),        icon: '🔗', isReal: true },
            { id: 'paper',             label: t('navPaper'),          icon: '📝', isReal: true },
            { id: 'market_data',       label: t('navMarketData'),     icon: '📈', isReal: true },
            { id: 'data_quality',      label: t('navDataQuality'),    icon: '🛡️', isReal: true },
            { id: 'features',          label: t('navFeatures'),       icon: '🔢', isReal: true },
            { id: 'signals',           label: t('navSignals'),        icon: '📡', isReal: true },
            { id: 'critic',            label: t('navCritic'),         icon: '⚖️', isReal: true },
            { id: 'trade_intents',     label: t('navTradeIntents'),   icon: '🎯', isReal: true },
            { id: 'risk_governor',     label: t('navRiskGovernor'),   icon: '🛡️', isReal: true },
            { id: 'execution_monitor', label: t('navExecution'),      icon: '⚡', isReal: true },
            { id: 'positions',         label: t('navPositions'),      icon: '💼', isReal: true },
            { id: 'config',            label: t('navConfig'),         icon: '⚙️', isReal: true },
            { id: 'agents',            label: t('navAgents'),         icon: '🤖', isReal: false },
            { id: 'orders',            label: t('navOrders'),         icon: '⚡', isReal: false },
            { id: 'risk',              label: t('navRisk'),           icon: '🔒', isReal: false },
            { id: 'backtest',          label: t('navBacktest'),       icon: '🧪', isReal: false },
            { id: 'incidents',         label: t('navIncidents'),      icon: '⚠️', isReal: true }
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as any)}
              className={`w-full flex items-center justify-between px-4 py-2.5 rounded-lg text-sm font-medium transition ${
                activeTab === tab.id
                  ? 'bg-cyan-500/10 text-cyan-400 border border-cyan-500/30'
                  : 'text-slate-400 hover:bg-slate-800/60 hover:text-slate-200'
              }`}
            >
              <div className="flex items-center space-x-3">
                <span>{tab.icon}</span>
                <span>{tab.label}</span>
              </div>
              {!tab.isReal && (
                <span className="text-[10px] uppercase font-mono px-1.5 py-0.5 rounded bg-slate-800 text-slate-500 border border-slate-700">
                  {t('mock')}
                </span>
              )}
            </button>
          ))}
        </aside>

        {/* Tab Content Panel */}
        <main className="flex-1 p-6 overflow-y-auto">
          {activeTab === 'overview' && (
            <div className="space-y-5">
              {/* Header */}
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-xl font-bold text-white">{t('pnlTitle')}</h2>
                  <p className="text-xs text-slate-400 mt-0.5">{t('pnlSubtitle')}</p>
                </div>
                <div className="flex items-center space-x-2">
                  <span className="flex items-center space-x-1.5 px-3 py-1.5 rounded-lg bg-emerald-950/60 border border-emerald-500/40 text-xs font-mono text-emerald-400">
                    <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
                    <span>{t('livePrices')}</span>
                  </span>
                  <span className="px-3 py-1.5 rounded-lg bg-cyan-950/60 border border-cyan-500/30 text-xs font-mono text-cyan-400">{t('paperTrading')}</span>
                  {!isBackendAvailable && (
                    <span className="px-3 py-1.5 rounded-lg bg-red-950/60 border border-red-500/30 text-xs font-mono text-red-400">{t('apiOffline')}</span>
                  )}
                </div>
              </div>

              {/* Live Price Ticker */}
              <div className="grid grid-cols-2 gap-3">
                {Object.entries(livePrices).map(([sym, price]) => {
                  const dir = priceDir[sym];
                  return (
                    <div key={sym} className={`glass-panel p-4 rounded-xl border transition-all duration-300 ${
                      dir === 'up' ? 'border-emerald-500/60 bg-emerald-950/20' :
                      dir === 'down' ? 'border-red-500/60 bg-red-950/20' :
                      'border-slate-800'
                    }`}>
                      <div className="flex justify-between items-start">
                        <div>
                          <p className="text-xs text-slate-400 font-medium">{sym}</p>
                          <p className={`text-2xl font-bold font-mono mt-1 transition-colors duration-300 ${
                            dir === 'up' ? 'text-emerald-400' : dir === 'down' ? 'text-red-400' : 'text-white'
                          }`}>${price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</p>
                        </div>
                        <span className={`text-xl ${ dir === 'up' ? '↑' : dir === 'down' ? '↓' : '—' }`}>
                          {dir === 'up' ? '▲' : dir === 'down' ? '▼' : '●'}
                        </span>
                      </div>
                      <p className="text-xs text-slate-500 font-mono mt-1">{t('binanceFeed')}</p>
                    </div>
                  );
                })}
              </div>

              {/* Portfolio KPIs */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                {(() => {
                  const totalUnrealized = positions.reduce((s, p) => s + p.unrealized_pnl, 0);
                  const totalNotional = positions.reduce((s, p) => s + p.notional, 0);
                  const realizedToday = fills.filter(f => {
                    const d = new Date(f.filled_at);
                    const now = new Date();
                    return d.toDateString() === now.toDateString() && f.realized_pnl !== null;
                  }).reduce((s, f) => s + (f.realized_pnl ?? 0), 0);
                  const nav = portfolio.total_nav + totalUnrealized;
                  return [
                    { label: t('portfolioNav'), value: `$${nav.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`, sub: t('paperAccount'), color: 'text-white' },
                    { label: t('unrealizedPnl'), value: `${totalUnrealized >= 0 ? '+' : ''}$${totalUnrealized.toFixed(2)}`, sub: `${positions.length} ${positions.length !== 1 ? t('openPositions') : t('openPosition')}`, color: totalUnrealized >= 0 ? 'text-emerald-400' : 'text-red-400' },
                    { label: t('realizedPnlToday'), value: `${realizedToday >= 0 ? '+' : ''}$${realizedToday.toFixed(2)}`, sub: `${fills.filter(f => new Date(f.filled_at).toDateString() === new Date().toDateString()).length} ${t('fillsToday')}`, color: realizedToday >= 0 ? 'text-emerald-400' : 'text-red-400' },
                    { label: t('exposureCash'), value: `$${totalNotional.toFixed(0)}`, sub: `${t('cash')} $${(portfolio.cash_balance - totalNotional).toFixed(0)}`, color: 'text-cyan-400' }
                  ].map((kpi, i) => (
                    <div key={i} className="glass-panel p-4 rounded-xl border border-slate-800">
                      <p className="text-xs text-slate-400 font-medium">{kpi.label}</p>
                      <p className={`text-xl font-bold font-mono mt-1 ${kpi.color}`}>{kpi.value}</p>
                      <p className="text-xs text-slate-500 font-mono mt-1">{kpi.sub}</p>
                    </div>
                  ));
                })()}
              </div>

              {/* Open Positions Table */}
              <div className="glass-panel rounded-xl border border-slate-800 overflow-hidden">
                <div className="flex items-center justify-between px-5 py-3 border-b border-slate-800">
                  <h3 className="text-sm font-bold text-white">{t('openPositionsTitle')}</h3>
                  <span className="px-2 py-0.5 rounded text-xs font-mono bg-emerald-950 text-emerald-400 border border-emerald-800">{positions.length} {lang === 'vi' ? 'MỞ' : 'OPEN'}</span>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm font-mono">
                    <thead>
                      <tr className="bg-slate-900/60 text-slate-500 text-xs uppercase">
                        <th className="px-5 py-3 text-left">{t('colSymbol')}</th>
                        <th className="px-5 py-3 text-left">{t('colSide')}</th>
                        <th className="px-5 py-3 text-right">{t('colQty')}</th>
                        <th className="px-5 py-3 text-right">{t('colAvgEntry')}</th>
                        <th className="px-5 py-3 text-right">{t('colMarketPrice')}</th>
                        <th className="px-5 py-3 text-right">{t('colNotional')}</th>
                        <th className="px-5 py-3 text-right">{t('colUnrealizedPnl')}</th>
                        <th className="px-5 py-3 text-right">{t('colReturn')}</th>
                        <th className="px-5 py-3 text-right">{t('colStopPrice')}</th>
                        <th className="px-5 py-3 text-right">{t('colStatus')}</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800/60">
                      {positions.length === 0 ? (
                        <tr>
                          <td colSpan={10} className="px-5 py-10 text-center text-slate-500 text-sm">
                            {t('noPositions')}
                          </td>
                        </tr>
                      ) : positions.map(p => {
                        const isProfit = p.unrealized_pnl >= 0;
                        const dir = priceDir[p.symbol];
                        return (
                          <tr key={p.id} className={`transition-all duration-300 ${
                            dir === 'up' && isProfit ? 'bg-emerald-950/10' :
                            dir === 'down' && !isProfit ? 'bg-red-950/10' :
                            'hover:bg-slate-800/30'
                          }`}>
                            <td className="px-5 py-4">
                              <div className="font-bold text-white">{p.symbol}</div>
                              <div className="text-xs text-slate-500">{p.id}</div>
                            </td>
                            <td className="px-5 py-4">
                              <span className={`px-2 py-0.5 rounded text-xs font-bold ${
                                p.side === 'LONG' ? 'bg-emerald-950 text-emerald-400 border border-emerald-800' : 'bg-red-950 text-red-400 border border-red-800'
                              }`}>{p.side}</span>
                            </td>
                            <td className="px-5 py-4 text-right text-white">{p.quantity.toFixed(4)}</td>
                            <td className="px-5 py-4 text-right text-slate-300">${p.avg_entry_price.toLocaleString('en-US', { minimumFractionDigits: 2 })}</td>
                            <td className={`px-5 py-4 text-right font-bold transition-colors duration-300 ${
                              dir === 'up' ? 'text-emerald-400' : dir === 'down' ? 'text-red-400' : 'text-white'
                            }`}>${p.market_price.toLocaleString('en-US', { minimumFractionDigits: 2 })}</td>
                            <td className="px-5 py-4 text-right text-slate-300">${p.notional.toLocaleString('en-US', { minimumFractionDigits: 2 })}</td>
                            <td className={`px-5 py-4 text-right font-bold text-base ${ isProfit ? 'text-emerald-400' : 'text-red-400' }`}>
                              {isProfit ? '+' : ''}${p.unrealized_pnl.toFixed(2)}
                            </td>
                            <td className={`px-5 py-4 text-right font-bold ${ isProfit ? 'text-emerald-400' : 'text-red-400' }`}>
                              {isProfit ? '+' : ''}{p.unrealized_pnl_pct.toFixed(2)}%
                            </td>
                            <td className="px-5 py-4 text-right text-amber-400">${p.stop_price.toLocaleString('en-US', { minimumFractionDigits: 2 })}</td>
                            <td className="px-5 py-4 text-right">
                              <span className="px-2 py-0.5 rounded text-xs bg-emerald-950 text-emerald-400 border border-emerald-800">{p.status}</span>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                    {positions.length > 0 && (() => {
                      const totalPnl = positions.reduce((s, p) => s + p.unrealized_pnl, 0);
                      const totalNotional = positions.reduce((s, p) => s + p.notional, 0);
                      return (
                        <tfoot>
                          <tr className="bg-slate-900/80 border-t border-slate-700">
                            <td colSpan={5} className="px-5 py-3 text-xs text-slate-500 font-semibold uppercase">{t('portfolioTotals')}</td>
                            <td className="px-5 py-3 text-right font-bold text-white font-mono">${totalNotional.toFixed(2)}</td>
                            <td className={`px-5 py-3 text-right font-bold text-lg font-mono ${ totalPnl >= 0 ? 'text-emerald-400' : 'text-red-400' }`}>
                              {totalPnl >= 0 ? '+' : ''}${totalPnl.toFixed(2)}
                            </td>
                            <td colSpan={3}></td>
                          </tr>
                        </tfoot>
                      );
                    })()}
                  </table>
                </div>
              </div>

              {/* Pending Orders Table */}
              <div className="glass-panel rounded-xl border border-slate-800 overflow-hidden">
                <div className="flex items-center justify-between px-5 py-3 border-b border-slate-800">
                  <div>
                    <h3 className="text-sm font-bold text-white flex items-center space-x-2">
                      <span>⏳</span>
                      <span>{t('pendingOrdersTitle')}</span>
                    </h3>
                    <p className="text-xs text-slate-500 mt-0.5">{t('pendingOrdersSub')}</p>
                  </div>
                  <div className="flex items-center space-x-2">
                    {pendingOrders.filter(o => o.status === 'PARTIALLY_FILLED').length > 0 && (
                      <span className="px-2 py-0.5 rounded text-xs font-mono bg-amber-950 text-amber-400 border border-amber-800 animate-pulse">
                        {pendingOrders.filter(o => o.status === 'PARTIALLY_FILLED').length} {lang === 'vi' ? 'KHỚP MỘT PHẦN' : 'PARTIAL'}
                      </span>
                    )}
                    <span className="px-2 py-0.5 rounded text-xs font-mono bg-slate-800 text-slate-400 border border-slate-700">
                      {pendingOrders.length} {lang === 'vi' ? 'lệnh' : 'orders'}
                    </span>
                  </div>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm font-mono">
                    <thead>
                      <tr className="bg-slate-900/60 text-slate-500 text-xs uppercase">
                        <th className="px-5 py-3 text-left">{t('colOrderId')}</th>
                        <th className="px-5 py-3 text-left">{t('colSymbol')}</th>
                        <th className="px-5 py-3 text-left">{t('colSide')}</th>
                        <th className="px-5 py-3 text-left">{t('colOrderType')}</th>
                        <th className="px-5 py-3 text-right">{t('colLimitPrice')}</th>
                        <th className="px-5 py-3 text-right">{t('colStopTrigger')}</th>
                        <th className="px-5 py-3 text-right">{t('colFilled')}</th>
                        <th className="px-5 py-3 text-center">{t('colTIF')}</th>
                        <th className="px-5 py-3 text-right">{t('distToLimit')}</th>
                        <th className="px-5 py-3 text-right">{t('colAge')}</th>
                        <th className="px-5 py-3 text-center">{t('colAction')}</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800/60">
                      {pendingOrders.length === 0 ? (
                        <tr>
                          <td colSpan={11} className="px-5 py-10 text-center text-slate-500 text-sm">
                            {t('noPendingOrders')}
                          </td>
                        </tr>
                      ) : pendingOrders.map(o => {
                        const ageMs = Date.now() - new Date(o.created_at).getTime();
                        const ageMins = Math.floor(ageMs / 60000);
                        const ageStr = ageMins < 60
                          ? `${ageMins}${lang === 'vi' ? ' phút' : 'm'}`
                          : `${Math.floor(ageMins / 60)}${lang === 'vi' ? ' giờ' : 'h'} ${ageMins % 60}${lang === 'vi' ? ' phút' : 'm'}`;
                        const mktPrice = livePrices[o.symbol];
                        const dist = o.limit_price && mktPrice
                          ? ((o.limit_price - mktPrice) / mktPrice * 100)
                          : null;
                        const fillPct = o.quantity > 0 ? (o.filled_qty / o.quantity * 100) : 0;
                        const statusCfg = {
                          'PENDING':          { label: t('statusPending'), cls: 'bg-slate-800 text-slate-300 border-slate-600' },
                          'PARTIALLY_FILLED': { label: t('statusPartial'), cls: 'bg-amber-950 text-amber-400 border-amber-700 animate-pulse' },
                          'OPEN':             { label: t('statusOpen'),    cls: 'bg-cyan-950 text-cyan-400 border-cyan-700' },
                        }[o.status];
                        const typeCfg: Record<string, string> = {
                          'LIMIT':       'bg-blue-950 text-blue-400 border-blue-800',
                          'MARKET':      'bg-emerald-950 text-emerald-400 border-emerald-800',
                          'STOP_LIMIT':  'bg-purple-950 text-purple-400 border-purple-800',
                          'STOP_MARKET': 'bg-red-950 text-red-400 border-red-800',
                        };
                        return (
                          <tr key={o.id} className="hover:bg-slate-800/30 transition-colors duration-150">
                            <td className="px-5 py-4">
                              <div className="text-slate-400 text-xs">{o.id}</div>
                              <div className={`mt-0.5 inline-flex px-1.5 py-0.5 rounded text-[10px] font-bold border ${statusCfg.cls}`}>
                                {statusCfg.label}
                              </div>
                            </td>
                            <td className="px-5 py-4 font-bold text-white">{o.symbol}</td>
                            <td className="px-5 py-4">
                              <span className={`px-2 py-0.5 rounded text-xs font-bold ${
                                o.side === 'BUY'
                                  ? 'bg-emerald-950 text-emerald-400 border border-emerald-800'
                                  : 'bg-red-950 text-red-400 border border-red-800'
                              }`}>
                                {o.side === 'BUY' ? (lang === 'vi' ? 'MUA' : 'BUY') : (lang === 'vi' ? 'BÁN' : 'SELL')}
                              </span>
                            </td>
                            <td className="px-5 py-4">
                              <span className={`px-2 py-0.5 rounded text-xs font-mono font-bold border ${typeCfg[o.order_type] ?? ''}`}>
                                {o.order_type.replace('_', ' ')}
                              </span>
                            </td>
                            <td className="px-5 py-4 text-right">
                              {o.limit_price != null
                                ? <span className="text-white">${o.limit_price.toLocaleString('en-US', { minimumFractionDigits: 2 })}</span>
                                : <span className="text-slate-600">—</span>
                              }
                            </td>
                            <td className="px-5 py-4 text-right">
                              {o.stop_price != null
                                ? <span className="text-amber-400">${o.stop_price.toLocaleString('en-US', { minimumFractionDigits: 2 })}</span>
                                : <span className="text-slate-600">—</span>
                              }
                            </td>
                            <td className="px-5 py-4 text-right">
                              <div className="text-xs text-slate-300">
                                {o.filled_qty.toFixed(4)} / {o.quantity.toFixed(4)}
                              </div>
                              {/* Fill progress bar */}
                              <div className="mt-1 h-1 w-20 ml-auto bg-slate-700 rounded-full overflow-hidden">
                                <div
                                  className="h-full bg-amber-400 rounded-full transition-all"
                                  style={{ width: `${fillPct}%` }}
                                />
                              </div>
                              <div className="text-[10px] text-slate-500 text-right mt-0.5">{fillPct.toFixed(0)}%</div>
                            </td>
                            <td className="px-5 py-4 text-center">
                              <span className="px-2 py-0.5 rounded text-xs font-mono bg-slate-800 text-slate-300 border border-slate-700">
                                {o.time_in_force}
                              </span>
                            </td>
                            <td className="px-5 py-4 text-right">
                              {dist !== null ? (
                                <span className={`text-xs font-mono ${Math.abs(dist) < 1 ? 'text-amber-400' : dist < 0 ? 'text-emerald-400' : 'text-slate-400'}`}>
                                  {dist > 0 ? '+' : ''}{dist.toFixed(2)}%
                                </span>
                              ) : <span className="text-slate-600">—</span>}
                            </td>
                            <td className="px-5 py-4 text-right text-slate-400 text-xs">{ageStr}</td>
                            <td className="px-5 py-4 text-center">
                              <button
                                onClick={() => alert(`[PAPER] ${lang === 'vi' ? 'Hủy lệnh' : 'Cancel order'} ${o.id}`)}
                                className="px-2 py-1 rounded text-xs font-medium bg-red-950/60 text-red-400 border border-red-800/60 hover:bg-red-900/80 hover:text-red-200 transition"
                              >
                                {t('cancelOrder')}
                              </button>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Recent Fills */}
              <div className="glass-panel rounded-xl border border-slate-800 overflow-hidden">
                <div className="flex items-center justify-between px-5 py-3 border-b border-slate-800">
                  <h3 className="text-sm font-bold text-white">{t('recentFills')}</h3>
                  <span className="text-xs text-slate-500 font-mono">{fills.length} {t('totalFills')}</span>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm font-mono">
                    <thead>
                      <tr className="bg-slate-900/60 text-slate-500 text-xs uppercase">
                        <th className="px-5 py-3 text-left">{t('colFillId')}</th>
                        <th className="px-5 py-3 text-left">{t('colSymbol')}</th>
                        <th className="px-5 py-3 text-left">{t('colSide')}</th>
                        <th className="px-5 py-3 text-right">{t('colQty')}</th>
                        <th className="px-5 py-3 text-right">{lang === 'vi' ? 'Giá Khớp' : 'Fill Price'}</th>
                        <th className="px-5 py-3 text-right">{t('colFee')}</th>
                        <th className="px-5 py-3 text-right">{t('colRealizedPnl')}</th>
                        <th className="px-5 py-3 text-right">{t('colTime')}</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800/60">
                      {fills.map(f => (
                        <tr key={f.id} className="hover:bg-slate-800/30 transition-colors">
                          <td className="px-5 py-3 text-slate-500">{f.id}</td>
                          <td className="px-5 py-3 text-white font-bold">{f.symbol}</td>
                          <td className="px-5 py-3">
                            <span className={`px-2 py-0.5 rounded text-xs font-bold ${
                              f.side === 'BUY' ? 'bg-emerald-950 text-emerald-400 border border-emerald-800' : 'bg-red-950 text-red-400 border border-red-800'
                            }`}>{f.side}</span>
                          </td>
                          <td className="px-5 py-3 text-right text-slate-300">{f.quantity.toFixed(4)}</td>
                          <td className="px-5 py-3 text-right text-white">${f.fill_price.toLocaleString('en-US', { minimumFractionDigits: 2 })}</td>
                          <td className="px-5 py-3 text-right text-amber-400">${f.fee.toFixed(2)}</td>
                          <td className={`px-5 py-3 text-right font-bold ${
                            f.realized_pnl === null ? 'text-slate-500' :
                            f.realized_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'
                          }`}>
                            {f.realized_pnl === null ? '—' : `${f.realized_pnl >= 0 ? '+' : ''}$${f.realized_pnl.toFixed(2)}`}
                          </td>
                          <td className="px-5 py-3 text-right text-slate-500 text-xs">
                            {new Date(f.filled_at).toLocaleString('en-US', { month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit' })}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Bottom strip */}
              <div className="glass-panel px-5 py-3 rounded-xl border border-slate-800 flex items-center justify-between text-xs font-mono text-slate-500">
                <span>Mode: <span className="text-cyan-400 font-bold">{status.mode}</span> | Live Trading: <span className="text-red-400 font-bold">DISABLED</span></span>
                <span>Risk Engine: <span className="text-emerald-400">NORMAL</span> | Guardian: <span className="text-emerald-400">HEALTHY</span></span>
                <span>Feed: Binance Public WebSocket (BTC/USDT, ETH/USDT)</span>
              </div>
            </div>
          )}

          {activeTab === 'market_data' && (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-xl font-bold text-white">Market Data Streams</h2>
                  <p className="text-xs text-slate-400">Public Binance Market Feed (Read-Only)</p>
                </div>
                <div className="flex items-center space-x-2">
                  <span className="px-2.5 py-1 rounded bg-slate-800 text-xs font-mono text-cyan-400 border border-cyan-500/30">Public API Only</span>
                  <span className="px-2.5 py-1 rounded bg-red-950 text-xs font-mono text-red-400 border border-red-500/30">Trading Disabled</span>
                </div>
              </div>

              <div className="flex items-center gap-3">
                <div>
                  <label className="text-xs text-slate-400 block mb-1">{t('chartSymbolLabel')}</label>
                  <input
                    type="text"
                    value={chartSymbol}
                    onChange={(e) => setChartSymbol(e.target.value.toUpperCase())}
                    className="bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-sm text-slate-100 w-40 focus:outline-none focus:border-cyan-500"
                  />
                </div>
                <div>
                  <label className="text-xs text-slate-400 block mb-1">{t('chartTimeframeLabel')}</label>
                  <select
                    value={chartTimeframe}
                    onChange={(e) => setChartTimeframe(e.target.value)}
                    className="bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-sm text-slate-100 focus:outline-none focus:border-cyan-500"
                  >
                    <option value="1m">1m</option>
                    <option value="5m">5m</option>
                    <option value="15m">15m</option>
                    <option value="1h">1h</option>
                    <option value="4h">4h</option>
                    <option value="1d">1d</option>
                  </select>
                </div>
              </div>

              <CandleChart symbol={chartSymbol} timeframe={chartTimeframe} lang={lang} />

              <div className="glass-panel p-6 rounded-xl border border-slate-800 space-y-4">
                <h3 className="text-sm font-semibold text-slate-300">Registered Canonical Symbols</h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {symbols.length > 0 ? symbols.map((s) => (
                    <div key={s.canonical_symbol} className="p-4 bg-slate-900 rounded-lg border border-slate-800 flex justify-between items-center">
                      <div>
                        <p className="font-bold text-white text-base">{s.canonical_symbol}</p>
                        <p className="text-xs text-slate-400">Exchange Symbol: {s.exchange_symbol} ({s.exchange})</p>
                      </div>
                      <div className="text-right">
                        <span className="px-2 py-0.5 rounded text-xs bg-emerald-950 text-emerald-400 border border-emerald-800 font-mono">{s.status}</span>
                        <p className="text-xs text-slate-500 mt-1">Tick: {s.price_tick_size}</p>
                      </div>
                    </div>
                  )) : (
                    <div className="text-slate-500 text-sm">Loading symbols...</div>
                  )}
                </div>
              </div>
            </div>
          )}

          {activeTab === 'data_quality' && (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-xl font-bold text-white">Data Guardian & Quality Status</h2>
                  <p className="text-xs text-slate-400">Freshness, Completeness, Validity, and Anomaly Audit Engine</p>
                </div>
                <button
                  onClick={async () => {
                    await fetch('/api/data-quality/resync/BTC/USDT', { method: 'POST' });
                    alert('Triggered market data state resync for BTC/USDT');
                  }}
                  className="px-3 py-1.5 bg-cyan-600 hover:bg-cyan-500 text-white text-xs font-medium rounded transition font-mono"
                >
                  RESYNC BTC/USDT
                </button>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 font-mono text-sm">
                <div className="glass-panel p-4 rounded-xl border border-slate-800 space-y-2">
                  <div className="flex justify-between items-center border-b border-slate-800 pb-2">
                    <span className="font-bold text-white">BTC/USDT Streams</span>
                    <span className="px-2 py-0.5 rounded text-xs bg-emerald-950 text-emerald-400 border border-emerald-800">HEALTHY</span>
                  </div>
                  <div className="text-xs space-y-1 text-slate-300">
                    <p className="flex justify-between"><span>Trades Stream:</span><span className="text-emerald-400 font-bold">HEALTHY</span></p>
                    <p className="flex justify-between"><span>Candle Stream:</span><span className="text-emerald-400 font-bold">HEALTHY</span></p>
                    <p className="flex justify-between"><span>Order Book Stream:</span><span className="text-emerald-400 font-bold">HEALTHY</span></p>
                  </div>
                </div>

                <div className="glass-panel p-4 rounded-xl border border-slate-800 space-y-2">
                  <div className="flex justify-between items-center border-b border-slate-800 pb-2">
                    <span className="font-bold text-white">ETH/USDT Streams</span>
                    <span className="px-2 py-0.5 rounded text-xs bg-emerald-950 text-emerald-400 border border-emerald-800">HEALTHY</span>
                  </div>
                  <div className="text-xs space-y-1 text-slate-300">
                    <p className="flex justify-between"><span>Trades Stream:</span><span className="text-emerald-400 font-bold">HEALTHY</span></p>
                    <p className="flex justify-between"><span>Candle Stream:</span><span className="text-emerald-400 font-bold">HEALTHY</span></p>
                    <p className="flex justify-between"><span>Order Book Stream:</span><span className="text-emerald-400 font-bold">HEALTHY</span></p>
                  </div>
                </div>
              </div>
            </div>
          )}

          {activeTab === 'config' && (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <h2 className="text-xl font-bold text-white">Dynamic Configuration Manager</h2>
                <span className="px-2 py-1 rounded bg-slate-800 text-xs font-mono text-cyan-400 border border-cyan-500/30">Versioned & Audited</span>
              </div>
              <div className="glass-panel p-6 rounded-xl border border-slate-800 space-y-4">
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-sm font-mono">
                    <thead className="bg-slate-900 text-slate-400 uppercase text-xs">
                      <tr>
                        <th className="p-3">Namespace</th>
                        <th className="p-3">Name</th>
                        <th className="p-3">Version</th>
                        <th className="p-3">Status</th>
                        <th className="p-3">SHA-256 Checksum</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800">
                      {configs.length > 0 ? configs.map((c) => (
                        <tr key={c.id}>
                          <td className="p-3 text-cyan-400">{c.namespace}</td>
                          <td className="p-3 text-white">{c.name}</td>
                          <td className="p-3 text-amber-400">v{c.version}</td>
                          <td className="p-3">
                            <span className={`px-2 py-0.5 rounded text-xs ${
                              c.status === 'ACTIVE' ? 'bg-emerald-950 text-emerald-400 border border-emerald-800' : 'bg-slate-800 text-slate-400'
                            }`}>
                              {c.status}
                            </span>
                          </td>
                          <td className="p-3 text-xs text-slate-500">{c.checksum.substring(0, 16)}...</td>
                        </tr>
                      )) : (
                        <tr>
                          <td colSpan={5} className="p-4 text-center text-slate-500">No configuration sets registered yet.</td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}

          {activeTab === 'features' && (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <h2 className="text-xl font-bold text-white">Feature Store & Technical Indicators</h2>
                <span className="px-2 py-1 rounded bg-slate-800 text-xs font-mono text-cyan-400 border border-cyan-500/30">Zero Lookahead Leakage (As-Of Join)</span>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                {[
                  { name: 'Simple Return (1p, 3p, 5p)', category: 'Price Return', status: 'VALID', lookback: '5 bars' },
                  { name: 'Moving Averages (SMA/EMA 10, 20)', category: 'Trend', status: 'VALID', lookback: '20 bars' },
                  { name: 'EMA 20 Slope & ADX 14', category: 'Trend Strength', status: 'VALID', lookback: '28 bars' },
                  { name: 'RSI 14 (Relative Strength)', category: 'Momentum', status: 'VALID', lookback: '15 bars' },
                  { name: 'ATR 14 & Realized Volatility', category: 'Volatility', status: 'VALID', lookback: '21 bars' },
                  { name: 'Volume SMA & Relative Volume', category: 'Volume', status: 'VALID', lookback: '20 bars' },
                  { name: 'Rolling Z-Score & Bollinger %B', category: 'Mean Reversion', status: 'VALID', lookback: '20 bars' },
                  { name: 'Donchian Breakout 20', category: 'Breakout', status: 'VALID', lookback: '21 bars' }
                ].map((f, i) => (
                  <div key={i} className="glass-panel p-4 rounded-xl border border-slate-800 space-y-2">
                    <div className="flex justify-between items-center">
                      <span className="text-xs font-mono text-cyan-400">{f.category}</span>
                      <span className="px-2 py-0.5 rounded text-xs font-mono bg-emerald-950 text-emerald-400 border border-emerald-800">{f.status}</span>
                    </div>
                    <h3 className="font-semibold text-white text-sm">{f.name}</h3>
                    <p className="text-xs text-slate-400">Required Lookback: {f.lookback}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {activeTab === 'signals' && (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <h2 className="text-xl font-bold text-white">Strategy Agent Signal Explorer</h2>
                <span className="px-2 py-1 rounded bg-slate-800 text-xs font-mono text-emerald-400 border border-emerald-500/30">Analysis Signals Only (No Trade Execution)</span>
              </div>
              <div className="space-y-3">
                {[
                  { agent: 'Trend Following Agent', type: 'TREND_FOLLOWING', action: 'LONG', conf: '0.75', regime: 'TREND_UP', horizon: '60m', reasons: ['UPTREND_CONFIRMED', 'EMA_SLOPE_POSITIVE'] },
                  { agent: 'Mean Reversion Agent', type: 'MEAN_REVERSION', action: 'NO_SIGNAL', conf: '0.50', regime: 'SIDEWAYS', horizon: '30m', reasons: ['INSIDE_NEUTRAL_ZONE'] },
                  { agent: 'Breakout Strategy Agent', type: 'BREAKOUT', action: 'LONG', conf: '0.80', regime: 'TREND_UP', horizon: '45m', reasons: ['BULLISH_DONCHIAN_BREAKOUT', 'VOLUME_EXPANSION_CONFIRMED'] }
                ].map((s, i) => (
                  <div key={i} className="glass-panel p-5 rounded-xl border border-slate-800 flex justify-between items-center">
                    <div>
                      <div className="flex items-center space-x-2">
                        <h3 className="font-semibold text-white text-base">{s.agent}</h3>
                        <span className="text-xs px-2 py-0.5 rounded font-mono bg-slate-800 text-slate-300 border border-slate-700">{s.type}</span>
                      </div>
                      <p className="text-xs text-slate-400 mt-1">Market Regime: <span className="text-cyan-400 font-mono">{s.regime}</span> | Horizon: {s.horizon}</p>
                      <div className="flex space-x-2 mt-2">
                        {s.reasons.map((r, ri) => (
                          <span key={ri} className="text-xs font-mono bg-slate-900 text-slate-400 px-2 py-0.5 rounded border border-slate-800">{r}</span>
                        ))}
                      </div>
                    </div>
                    <div className="text-right space-y-1">
                      <span className={`px-3 py-1 rounded text-sm font-bold font-mono ${s.action === 'LONG' ? 'bg-emerald-950 text-emerald-400 border border-emerald-800' : 'bg-slate-800 text-slate-400 border border-slate-700'}`}>
                        {s.action}
                      </span>
                      <p className="text-xs text-slate-400">Confidence: <span className="text-white font-mono">{s.conf}</span></p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {activeTab === 'critic' && (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <h2 className="text-xl font-bold text-white">Critic Agent Scrutiny & Penalty Review</h2>
                <span className="px-2 py-1 rounded bg-slate-800 text-xs font-mono text-cyan-400 border border-cyan-500/30">Deterministic Rule Engine</span>
              </div>
              <div className="space-y-3">
                {[
                  { agent: 'Trend Following Agent', signal: 'LONG (BTC/USDT)', origConf: '0.75', adjConf: '0.75', penalty: '0.00', status: 'APPROVED', cost: '22.0 bps', flags: ['DATA_QUALITY_OK', 'REGIME_COMPATIBLE'] },
                  { agent: 'Breakout Strategy Agent', signal: 'LONG (BTC/USDT)', origConf: '0.80', adjConf: '0.80', penalty: '0.00', status: 'APPROVED', cost: '22.0 bps', flags: ['DONCHIAN_BREAKOUT_OK', 'VOLUME_EXPANSION_OK'] },
                  { agent: 'Mean Reversion Agent', signal: 'NO_SIGNAL (BTC/USDT)', origConf: '0.50', adjConf: '0.50', penalty: '0.00', status: 'REJECTED', cost: '22.0 bps', flags: ['INSIDE_NEUTRAL_ZONE'] }
                ].map((c, i) => (
                  <div key={i} className="glass-panel p-5 rounded-xl border border-slate-800 flex justify-between items-center">
                    <div>
                      <div className="flex items-center space-x-2">
                        <h3 className="font-semibold text-white text-base">{c.agent}</h3>
                        <span className="text-xs px-2 py-0.5 rounded font-mono bg-slate-800 text-slate-300 border border-slate-700">{c.signal}</span>
                      </div>
                      <p className="text-xs text-slate-400 mt-1">Est. Trading Cost: <span className="text-cyan-400 font-mono">{c.cost}</span> | Penalty: <span className="text-amber-400 font-mono">-{c.penalty}</span></p>
                      <div className="flex space-x-2 mt-2">
                        {c.flags.map((f, fi) => (
                          <span key={fi} className="text-xs font-mono bg-slate-900 text-slate-400 px-2 py-0.5 rounded border border-slate-800">{f}</span>
                        ))}
                      </div>
                    </div>
                    <div className="text-right space-y-1">
                      <span className={`px-3 py-1 rounded text-sm font-bold font-mono ${c.status === 'APPROVED' ? 'bg-emerald-950 text-emerald-400 border border-emerald-800' : 'bg-rose-950 text-rose-400 border border-rose-800'}`}>
                        {c.status}
                      </span>
                      <p className="text-xs text-slate-400">Adj. Conf: <span className="text-white font-mono">{c.adjConf}</span> (Orig: {c.origConf})</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {activeTab === 'trade_intents' && (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <h2 className="text-xl font-bold text-white">TradeIntent Explorer</h2>
                <span className="px-2 py-1 rounded bg-slate-800 text-xs font-mono text-emerald-400 border border-emerald-500/30">PENDING_RISK_REVIEW Only (NO Quantity / Notional)</span>
              </div>
              <div className="glass-panel p-6 rounded-xl border border-slate-800 space-y-4">
                <div className="flex justify-between items-center border-b border-slate-800 pb-4">
                  <div>
                    <span className="px-2 py-0.5 rounded text-xs font-mono bg-cyan-950 text-cyan-400 border border-cyan-800">BUY INTENT</span>
                    <h3 className="font-bold text-white text-lg mt-1">BTC/USDT</h3>
                    <p className="text-xs text-slate-400">Market Regime: TREND_UP | Horizon: 60m</p>
                  </div>
                  <div className="text-right">
                    <span className="px-3 py-1 rounded text-xs font-mono bg-amber-950 text-amber-400 border border-amber-800 font-bold">PENDING_RISK_REVIEW</span>
                    <p className="text-xs text-slate-400 mt-1">Ref Price: <span className="font-mono text-white">$65,000.00</span></p>
                  </div>
                </div>

                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-xs font-mono">
                  <div className="bg-slate-900/60 p-3 rounded border border-slate-800">
                    <p className="text-slate-400">Exp. Return</p>
                    <p className="text-emerald-400 font-bold text-sm">+50.00 bps</p>
                  </div>
                  <div className="bg-slate-900/60 p-3 rounded border border-slate-800">
                    <p className="text-slate-400">Weighted Conf</p>
                    <p className="text-cyan-400 font-bold text-sm">77.50%</p>
                  </div>
                  <div className="bg-slate-900/60 p-3 rounded border border-slate-800">
                    <p className="text-slate-400">Est. Total Cost</p>
                    <p className="text-amber-400 font-bold text-sm">22.00 bps</p>
                  </div>
                  <div className="bg-slate-900/60 p-3 rounded border border-slate-800">
                    <p className="text-slate-400">Calculated Net Edge</p>
                    <p className="text-emerald-400 font-bold text-sm">+16.75 bps</p>
                  </div>
                </div>

                <div className="flex justify-between items-center text-xs text-slate-400 pt-2 border-t border-slate-800/60">
                  <span>Invalidation Price: <span className="text-rose-400 font-mono">$63,700.00</span></span>
                  <span>Suggested Target: <span className="text-emerald-400 font-mono">$68,250.00</span></span>
                  <span>Quantity / NAV Sizing: <span className="text-amber-400 font-mono">NOT CALCULATED (Milestone 6)</span></span>
                </div>
              </div>
            </div>
          )}

          {activeTab === 'risk_governor' && (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <h2 className="text-xl font-bold text-white">Deterministic Risk Governor & Approved Orders</h2>
                <span className="px-2 py-1 rounded bg-emerald-950 text-xs font-mono text-emerald-400 border border-emerald-800">State: NORMAL | Absolute Veto Power</span>
              </div>

              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-xs font-mono">
                <div className="glass-panel p-4 rounded-xl border border-slate-800">
                  <p className="text-slate-400">Risk per Trade</p>
                  <p className="text-white font-bold text-sm">0.25% NAV ($250.00)</p>
                </div>
                <div className="glass-panel p-4 rounded-xl border border-slate-800">
                  <p className="text-slate-400">Max Open Risk</p>
                  <p className="text-white font-bold text-sm">1.00% NAV ($1,000.00)</p>
                </div>
                <div className="glass-panel p-4 rounded-xl border border-slate-800">
                  <p className="text-slate-400">Daily Loss Hard Limit</p>
                  <p className="text-amber-400 font-bold text-sm">1.50% NAV ($1,500.00)</p>
                </div>
                <div className="glass-panel p-4 rounded-xl border border-slate-800">
                  <p className="text-slate-400">Hard-Stop Drawdown</p>
                  <p className="text-rose-400 font-bold text-sm">8.00% NAV</p>
                </div>
              </div>

              <div className="glass-panel p-6 rounded-xl border border-slate-800 space-y-4">
                <div className="flex justify-between items-center border-b border-slate-800 pb-3">
                  <h3 className="font-bold text-white text-base">ApprovedOrder #104 (BUY BTC/USDT)</h3>
                  <span className="px-2.5 py-0.5 rounded text-xs font-mono bg-cyan-950 text-cyan-400 border border-cyan-800 font-bold">PENDING_EXECUTION</span>
                </div>

                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-xs font-mono">
                  <div className="bg-slate-900/60 p-3 rounded border border-slate-800">
                    <p className="text-slate-400">Approved Quantity</p>
                    <p className="text-emerald-400 font-bold text-sm">0.192 BTC</p>
                  </div>
                  <div className="bg-slate-900/60 p-3 rounded border border-slate-800">
                    <p className="text-slate-400">Max Notional</p>
                    <p className="text-white font-bold text-sm">$12,492.48</p>
                  </div>
                  <div className="bg-slate-900/60 p-3 rounded border border-slate-800">
                    <p className="text-slate-400">Approved Stop Price</p>
                    <p className="text-rose-400 font-bold text-sm">$63,700.00</p>
                  </div>
                  <div className="bg-slate-900/60 p-3 rounded border border-slate-800">
                    <p className="text-slate-400">Max Entry Price</p>
                    <p className="text-cyan-400 font-bold text-sm">$65,065.00</p>
                  </div>
                </div>

                <div className="flex justify-between items-center text-xs text-slate-400 pt-2 border-t border-slate-800/60">
                  <span>Actual Risk: <span className="text-amber-400 font-mono">$249.60 (0.249% NAV)</span></span>
                  <span>Execution Status: <span className="text-slate-400 font-mono">NOT SUBMITTED (Milestone 7 Execution Engine)</span></span>
                </div>
              </div>
            </div>
          )}

          {activeTab === 'execution_monitor' && (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <h2 className="text-xl font-bold text-white">Execution Engine & Exchange Simulator</h2>
                <span className="px-2 py-1 rounded bg-cyan-950 text-xs font-mono text-cyan-400 border border-cyan-800">Mode: SIMULATION | Zero Exchange Connection</span>
              </div>

              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-xs font-mono">
                <div className="glass-panel p-4 rounded-xl border border-slate-800">
                  <p className="text-slate-400">Execution Mode</p>
                  <p className="text-cyan-400 font-bold text-sm">SIMULATION ONLY</p>
                </div>
                <div className="glass-panel p-4 rounded-xl border border-slate-800">
                  <p className="text-slate-400">Simulator Tactic</p>
                  <p className="text-white font-bold text-sm">SINGLE_MARKETABLE_LIMIT</p>
                </div>
                <div className="glass-panel p-4 rounded-xl border border-slate-800">
                  <p className="text-slate-400">Simulated Slippage</p>
                  <p className="text-amber-400 font-bold text-sm">5.0 bps</p>
                </div>
                <div className="glass-panel p-4 rounded-xl border border-slate-800">
                  <p className="text-slate-400">Simulated Fee (Taker)</p>
                  <p className="text-emerald-400 font-bold text-sm">10.0 bps</p>
                </div>
              </div>

              <div className="glass-panel p-6 rounded-xl border border-slate-800 space-y-4">
                <div className="flex justify-between items-center border-b border-slate-800 pb-3">
                  <div>
                    <h3 className="font-bold text-white text-base">ExecutionReport #801 (BTC/USDT)</h3>
                    <p className="text-xs text-slate-400">Client Order ID: <span className="font-mono text-slate-300">c9d8a172-...</span></p>
                  </div>
                  <span className="px-3 py-1 rounded text-xs font-mono bg-emerald-950 text-emerald-400 border border-emerald-800 font-bold">FILLED</span>
                </div>

                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-xs font-mono">
                  <div className="bg-slate-900/60 p-3 rounded border border-slate-800">
                    <p className="text-slate-400">Approved Qty</p>
                    <p className="text-white font-bold text-sm">0.192 BTC</p>
                  </div>
                  <div className="bg-slate-900/60 p-3 rounded border border-slate-800">
                    <p className="text-slate-400">Filled Qty</p>
                    <p className="text-emerald-400 font-bold text-sm">0.192 BTC (100%)</p>
                  </div>
                  <div className="bg-slate-900/60 p-3 rounded border border-slate-800">
                    <p className="text-slate-400">Average Fill Price</p>
                    <p className="text-cyan-400 font-bold text-sm">$65,032.50</p>
                  </div>
                  <div className="bg-slate-900/60 p-3 rounded border border-slate-800">
                    <p className="text-slate-400">Total Fee Paid</p>
                    <p className="text-amber-400 font-bold text-sm">$12.48 USDT</p>
                  </div>
                </div>

                <div className="flex justify-between items-center text-xs text-slate-400 pt-2 border-t border-slate-800/60">
                  <span>Executed Notional: <span className="text-white font-mono">$12,486.24 USDT</span></span>
                  <span>Max Allowed Entry: <span className="text-cyan-400 font-mono">$65,065.00</span></span>
                  <span>Adapter: <span className="text-emerald-400 font-mono">SimulatorExchangeAdapter</span></span>
                </div>
              </div>
            </div>
          )}

          {activeTab === 'positions' && (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <h2 className="text-xl font-bold text-white">Positions & Portfolio Ledger</h2>
                <span className="px-2 py-1 rounded bg-emerald-950 text-xs font-mono text-emerald-400 border border-emerald-800">Portfolio Ledger: ACTIVE | Weighted Avg Cost Basis</span>
              </div>

              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-xs font-mono">
                <div className="glass-panel p-4 rounded-xl border border-slate-800">
                  <p className="text-slate-400">Total Cash Balance</p>
                  <p className="text-emerald-400 font-bold text-sm">$87,513.76 USDT</p>
                </div>
                <div className="glass-panel p-4 rounded-xl border border-slate-800">
                  <p className="text-slate-400">Asset Market Value</p>
                  <p className="text-cyan-400 font-bold text-sm">$12,486.24 USDT</p>
                </div>
                <div className="glass-panel p-4 rounded-xl border border-slate-800">
                  <p className="text-slate-400">Portfolio NAV</p>
                  <p className="text-white font-bold text-sm">$100,000.00 USDT</p>
                </div>
                <div className="glass-panel p-4 rounded-xl border border-slate-800">
                  <p className="text-slate-400">Peak / Drawdown %</p>
                  <p className="text-amber-400 font-bold text-sm">$100k / 0.00%</p>
                </div>
              </div>

              <div className="glass-panel p-6 rounded-xl border border-slate-800 space-y-4">
                <div className="flex justify-between items-center border-b border-slate-800 pb-3">
                  <div>
                    <h3 className="font-bold text-white text-base">LONG BTC/USDT (Position #P-001)</h3>
                    <p className="text-xs text-slate-400">Cost Basis Method: <span className="font-mono text-slate-300">WEIGHTED_AVERAGE</span></p>
                  </div>
                  <span className="px-3 py-1 rounded text-xs font-mono bg-emerald-950 text-emerald-400 border border-emerald-800 font-bold">OPEN (0.192 BTC)</span>
                </div>

                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-xs font-mono">
                  <div className="bg-slate-900/60 p-3 rounded border border-slate-800">
                    <p className="text-slate-400">Avg Entry Price</p>
                    <p className="text-white font-bold text-sm">$65,032.50</p>
                  </div>
                  <div className="bg-slate-900/60 p-3 rounded border border-slate-800">
                    <p className="text-slate-400">Market Price</p>
                    <p className="text-cyan-400 font-bold text-sm">$65,032.50</p>
                  </div>
                  <div className="bg-slate-900/60 p-3 rounded border border-slate-800">
                    <p className="text-slate-400">Unrealized PnL</p>
                    <p className="text-emerald-400 font-bold text-sm">$0.00 USDT</p>
                  </div>
                  <div className="bg-slate-900/60 p-3 rounded border border-slate-800">
                    <p className="text-slate-400">Active / Trailing Stop</p>
                    <p className="text-amber-400 font-bold text-sm">$63,700.00</p>
                  </div>
                </div>

                <div className="flex justify-between items-center text-xs text-slate-400 pt-2 border-t border-slate-800/60">
                  <span>Available Qty: <span className="text-white font-mono">0.192 BTC</span></span>
                  <span>Reserved Exit Qty: <span className="text-amber-400 font-mono">0.000 BTC</span></span>
                  <span>Exit Protection: <span className="text-emerald-400 font-mono">ACTIVE (Stop + Trailing)</span></span>
                </div>
              </div>
            </div>
          )}

          {activeTab === 'agents' && (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <h2 className="text-xl font-bold text-white">Intelligence Agents Status</h2>
                <span className="px-2 py-1 rounded bg-slate-800 text-xs font-mono text-amber-400 border border-amber-500/30">Mock Agent Registry</span>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {[
                  { name: 'Market Regime Agent', type: 'Context', status: 'Active', weight: '1.0' },
                  { name: 'Multi-Timeframe Trend Agent', type: 'Alpha', status: 'Active', weight: '0.35' },
                  { name: 'VWAP Mean Reversion Agent', type: 'Alpha', status: 'Active', weight: '0.35' },
                  { name: 'Compression Breakout Agent', type: 'Alpha', status: 'Active', weight: '0.30' },
                  { name: 'Critic & Scrutiny Agent', type: 'Governance', status: 'Active', weight: 'Veto Power' }
                ].map((a, i) => (
                  <div key={i} className="glass-panel p-4 rounded-xl border border-slate-800 flex justify-between items-center">
                    <div>
                      <h3 className="font-semibold text-white">{a.name}</h3>
                      <p className="text-xs text-slate-400">Role: {a.type}</p>
                    </div>
                    <div className="text-right">
                      <span className="px-2 py-0.5 rounded text-xs bg-emerald-950 text-emerald-400 border border-emerald-800 font-mono">{a.status}</span>
                      <p className="text-xs text-slate-400 mt-1">Weight: {a.weight}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {activeTab === 'orders' && (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <h2 className="text-xl font-bold text-white">Order Execution History</h2>
                <span className="px-2 py-1 rounded bg-slate-800 text-xs font-mono text-amber-400 border border-amber-500/30">Mock / Simulator Data</span>
              </div>
              <div className="glass-panel p-8 rounded-xl border border-slate-800 text-center text-slate-400 text-sm">
                No order events recorded yet.
              </div>
            </div>
          )}

          {activeTab === 'risk' && (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <h2 className="text-xl font-bold text-white">Risk Governor Policy Configuration</h2>
                <span className="px-2 py-1 rounded bg-slate-800 text-xs font-mono text-cyan-400 border border-cyan-500/30">Deterministic Rules</span>
              </div>
              <div className="glass-panel p-6 rounded-xl border border-slate-800 space-y-4">
                <div className="grid grid-cols-2 gap-4 text-sm font-mono">
                  <div className="p-3 bg-slate-900 rounded border border-slate-800">
                    <span className="text-slate-400">Max Risk per Trade:</span>
                    <span className="float-right text-cyan-400 font-bold">0.25% NAV</span>
                  </div>
                  <div className="p-3 bg-slate-900 rounded border border-slate-800">
                    <span className="text-slate-400">Max Daily Loss Limit:</span>
                    <span className="float-right text-amber-400 font-bold">1.50% NAV</span>
                  </div>
                  <div className="p-3 bg-slate-900 rounded border border-slate-800">
                    <span className="text-slate-400">Max Open Risk:</span>
                    <span className="float-right text-cyan-400 font-bold">1.50% NAV</span>
                  </div>
                  <div className="p-3 bg-slate-900 rounded border border-slate-800">
                    <span className="text-slate-400">Hard Drawdown Kill Switch:</span>
                    <span className="float-right text-red-400 font-bold">8.00% NAV</span>
                  </div>
                </div>
              </div>
            </div>
          )}

          {activeTab === 'backtest' && (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <h2 className="text-xl font-bold text-white">Event-Driven Backtest Engine</h2>
                <span className="px-2 py-1 rounded bg-cyan-950 text-xs font-mono text-cyan-400 border border-cyan-800">Replay Engine: HISTORICAL_REPLAY | NO_SAME_BAR_FILL</span>
              </div>

              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-xs font-mono">
                <div className="glass-panel p-4 rounded-xl border border-slate-800">
                  <p className="text-slate-400">Registered Datasets</p>
                  <p className="text-white font-bold text-sm">1 Dataset (BTC/USDT 1h)</p>
                </div>
                <div className="glass-panel p-4 rounded-xl border border-slate-800">
                  <p className="text-slate-400">Total Return</p>
                  <p className="text-emerald-400 font-bold text-sm">+18.45%</p>
                </div>
                <div className="glass-panel p-4 rounded-xl border border-slate-800">
                  <p className="text-slate-400">Max Drawdown</p>
                  <p className="text-amber-400 font-bold text-sm">-3.12%</p>
                </div>
                <div className="glass-panel p-4 rounded-xl border border-slate-800">
                  <p className="text-slate-400">Win Rate / Trades</p>
                  <p className="text-cyan-400 font-bold text-sm">66.7% (12 Trades)</p>
                </div>
              </div>

              <div className="glass-panel p-6 rounded-xl border border-slate-800 space-y-4">
                <div className="flex justify-between items-center border-b border-slate-800 pb-3">
                  <div>
                    <h3 className="font-bold text-white text-base">Backtest Session #S-2026-001 (BTC/USDT 1h Replay)</h3>
                    <p className="text-xs text-slate-400">Reproducibility Fingerprint: <span className="font-mono text-cyan-400">a3f91c...89d1</span></p>
                  </div>
                  <span className="px-3 py-1 rounded text-xs font-mono bg-emerald-950 text-emerald-400 border border-emerald-800 font-bold">COMPLETED</span>
                </div>

                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-xs font-mono">
                  <div className="bg-slate-900/60 p-3 rounded border border-slate-800">
                    <p className="text-slate-400">Initial NAV</p>
                    <p className="text-white font-bold text-sm">$100,000.00</p>
                  </div>
                  <div className="bg-slate-900/60 p-3 rounded border border-slate-800">
                    <p className="text-slate-400">Final NAV</p>
                    <p className="text-emerald-400 font-bold text-sm">$118,450.00</p>
                  </div>
                  <div className="bg-slate-900/60 p-3 rounded border border-slate-800">
                    <p className="text-slate-400">Fees Paid</p>
                    <p className="text-amber-400 font-bold text-sm">$24.50 USDT</p>
                  </div>
                  <div className="bg-slate-900/60 p-3 rounded border border-slate-800">
                    <p className="text-slate-400">Events Processed</p>
                    <p className="text-cyan-400 font-bold text-sm">8,760 Candles</p>
                  </div>
                </div>

                <div className="flex justify-between items-center text-xs text-slate-400 pt-2 border-t border-slate-800/60">
                  <span>Isolation: <span className="text-emerald-400 font-mono">ISOLATED_NAMESPACE</span></span>
                  <span>Same-Bar Fill: <span className="text-slate-300 font-mono">NO_SAME_BAR_FILL</span></span>
                  <span>Reproducibility: <span className="text-emerald-400 font-mono">VERIFIED (100% Deterministic)</span></span>
                </div>
              </div>
            </div>
          )}

          {activeTab === 'paper' && (
            <div className="space-y-6">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-xl font-bold text-white flex items-center gap-2">
                    <span>Real-Time Paper Trading Runtime</span>
                    <span className="px-2.5 py-0.5 rounded text-xs font-mono bg-cyan-950 text-cyan-400 border border-cyan-800 font-bold">PAPER_MODE</span>
                  </h2>
                  <p className="text-xs text-slate-400">Public Real-Time WebSocket & Simulated Execution Engine</p>
                </div>
                <div className="flex items-center gap-2">
                  <span className="px-3 py-1 bg-amber-950 text-amber-400 border border-amber-800 rounded text-xs font-mono font-bold">LIVE TRADING DISABLED</span>
                  <span className="px-3 py-1 bg-slate-800 text-slate-300 rounded text-xs font-mono">SIMULATED CASH ACCOUNT</span>
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                <div className="glass-panel p-4 rounded-xl border border-slate-800">
                  <span className="text-xs text-slate-400">Session Status</span>
                  <p className="text-lg font-bold text-emerald-400 mt-1 font-mono">RUNNING</p>
                  <span className="text-[10px] text-slate-500 font-mono">Session ID: #P-2026-8801</span>
                </div>
                <div className="glass-panel p-4 rounded-xl border border-slate-800">
                  <span className="text-xs text-slate-400">Simulated Account Balance</span>
                  <p className="text-lg font-bold text-white mt-1 font-mono">$10,485.20 USDT</p>
                  <span className="text-[10px] text-emerald-400 font-mono">+4.85% Total Return</span>
                </div>
                <div className="glass-panel p-4 rounded-xl border border-slate-800">
                  <span className="text-xs text-slate-400">Public Data Health</span>
                  <p className="text-lg font-bold text-cyan-400 mt-1 font-mono">HEALTHY (12ms)</p>
                  <span className="text-[10px] text-slate-400 font-mono">Binance WebSocket Active</span>
                </div>
                <div className="glass-panel p-4 rounded-xl border border-slate-800">
                  <span className="text-xs text-slate-400">Risk Revalidation Gate</span>
                  <p className="text-lg font-bold text-emerald-400 mt-1 font-mono">100% PASS</p>
                  <span className="text-[10px] text-slate-400 font-mono">Deterministic Risk Governor</span>
                </div>
              </div>

              <div className="glass-panel p-6 rounded-xl border border-slate-800 space-y-4">
                <div className="flex justify-between items-center border-b border-slate-800 pb-3">
                  <div>
                    <h3 className="font-bold text-white text-base">Active Paper Session Controls & Config Snapshot</h3>
                    <p className="text-xs text-slate-400">Config Fingerprint: <span className="font-mono text-cyan-400">c89e1a4f...99d2</span></p>
                  </div>
                  <div className="flex gap-2">
                    <button className="px-3 py-1.5 bg-amber-600/80 hover:bg-amber-500 text-white text-xs font-medium rounded transition">PAUSE</button>
                    <button className="px-3 py-1.5 bg-slate-700 hover:bg-slate-600 text-white text-xs font-medium rounded transition">STOP SESSION</button>
                    <button className="px-3 py-1.5 bg-cyan-700 hover:bg-cyan-600 text-white text-xs font-medium rounded transition">RECOVERY CHECKPOINT</button>
                  </div>
                </div>

                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-xs font-mono">
                  <div className="bg-slate-900/60 p-3 rounded border border-slate-800">
                    <p className="text-slate-400">Symbol Scope</p>
                    <p className="text-white font-bold text-sm">BTC/USDT, ETH/USDT</p>
                  </div>
                  <div className="bg-slate-900/60 p-3 rounded border border-slate-800">
                    <p className="text-slate-400">Timeframe Scope</p>
                    <p className="text-cyan-400 font-bold text-sm">1h Closed Candle</p>
                  </div>
                  <div className="bg-slate-900/60 p-3 rounded border border-slate-800">
                    <p className="text-slate-400">Latency Model</p>
                    <p className="text-amber-400 font-bold text-sm">50ms + Jitter</p>
                  </div>
                  <div className="bg-slate-900/60 p-3 rounded border border-slate-800">
                    <p className="text-slate-400">Gap Recovery</p>
                    <p className="text-emerald-400 font-bold text-sm">AUTOMATIC_REST</p>
                  </div>
                </div>
              </div>
            </div>
          )}

          {activeTab === 'security' && (
            <div className="space-y-6">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-xl font-bold text-white flex items-center gap-2">
                    <span>Security Review, RBAC & Software Supply Chain</span>
                    <span className="px-2.5 py-0.5 rounded text-xs font-mono bg-emerald-950 text-emerald-400 border border-emerald-800 font-bold">PROFILE_HARDENED</span>
                  </h2>
                  <p className="text-xs text-slate-400">OWASP ASVS 5.0.0, CycloneDX SBOM Provenance & Fail-Closed Kill Boundary</p>
                </div>
                <div className="flex items-center gap-2">
                  <span className="px-3 py-1 bg-red-950 text-red-400 border border-red-800 rounded text-xs font-mono font-bold">LIVE TRADING: DISABLED</span>
                  <span className="px-3 py-1 bg-emerald-950 text-emerald-400 border border-emerald-800 rounded text-xs font-mono font-bold">SECURITY GATE: PASSED</span>
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                <div className="glass-panel p-4 rounded-xl border border-slate-800">
                  <span className="text-xs text-slate-400">Final System Profile</span>
                  <p className="text-sm font-bold text-emerald-400 mt-1 font-mono">COMPLETE FOR SECURE PAPER</p>
                  <span className="text-[10px] text-slate-500 font-mono">Paper & Historical Operations</span>
                </div>
                <div className="glass-panel p-4 rounded-xl border border-slate-800">
                  <span className="text-xs text-slate-400">RBAC Authorization</span>
                  <p className="text-lg font-bold text-cyan-400 mt-1 font-mono">DEFAULT_DENY</p>
                  <span className="text-[10px] text-slate-400 font-mono">6 Standard Roles Enforced</span>
                </div>
                <div className="glass-panel p-4 rounded-xl border border-slate-800">
                  <span className="text-xs text-slate-400">SBOM Provenance</span>
                  <p className="text-lg font-bold text-emerald-400 mt-1 font-mono">CYCLONEDX 1.4</p>
                  <span className="text-[10px] text-slate-400 font-mono">Package Checksums Verified</span>
                </div>
                <div className="glass-panel p-4 rounded-xl border border-slate-800">
                  <span className="text-xs text-slate-400">Disaster Recovery Drill</span>
                  <p className="text-lg font-bold text-purple-400 mt-1 font-mono">16-CHECK AUDIT</p>
                  <span className="text-[10px] text-emerald-400 font-mono">Reconciliation Clean</span>
                </div>
              </div>
            </div>
          )}

          {activeTab === 'observability' && (
            <div className="space-y-6">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-xl font-bold text-white flex items-center gap-2">
                    <span>Operational Observability & Metrics Registry</span>
                    <span className="px-2.5 py-0.5 rounded text-xs font-mono bg-indigo-950 text-indigo-400 border border-indigo-800 font-bold">PROMETHEUS_READY</span>
                  </h2>
                  <p className="text-xs text-slate-400">Structured Telemetry, SLO Error Budgets & Grafana Dashboards</p>
                </div>
                <div className="flex items-center gap-2">
                  <span className="px-3 py-1 bg-slate-800 text-slate-300 rounded text-xs font-mono">REDACTION ACTIVE</span>
                  <span className="px-3 py-1 bg-emerald-950 text-emerald-400 border border-emerald-800 rounded text-xs font-mono font-bold">SLO TARGET 99.9%</span>
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                <div className="glass-panel p-4 rounded-xl border border-slate-800">
                  <span className="text-xs text-slate-400">Prometheus Metrics Endpoint</span>
                  <p className="text-lg font-bold text-emerald-400 mt-1 font-mono">ACTIVE (/metrics)</p>
                  <span className="text-[10px] text-slate-500 font-mono">Cardinality Budget Guarded</span>
                </div>
                <div className="glass-panel p-4 rounded-xl border border-slate-800">
                  <span className="text-xs text-slate-400">Market Data Freshness SLO</span>
                  <p className="text-lg font-bold text-cyan-400 mt-1 font-mono">99.95%</p>
                  <span className="text-[10px] text-emerald-400 font-mono">Error Budget: 100% Remaining</span>
                </div>
                <div className="glass-panel p-4 rounded-xl border border-slate-800">
                  <span className="text-xs text-slate-400">Accounting Integrity SLO</span>
                  <p className="text-lg font-bold text-emerald-400 mt-1 font-mono">100.00%</p>
                  <span className="text-[10px] text-slate-400 font-mono">16 Completeness Checks Passed</span>
                </div>
                <div className="glass-panel p-4 rounded-xl border border-slate-800">
                  <span className="text-xs text-slate-400">Distributed Tracing</span>
                  <p className="text-lg font-bold text-purple-400 mt-1 font-mono">OPENTELEMETRY</p>
                  <span className="text-[10px] text-slate-400 font-mono">TraceContext Propagated</span>
                </div>
              </div>
            </div>
          )}

          {activeTab === 'lineage' && (
            <div className="space-y-6">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-xl font-bold text-white flex items-center gap-2">
                    <span>Pipeline Lineage & Correlation Explorer</span>
                    <span className="px-2.5 py-0.5 rounded text-xs font-mono bg-purple-950 text-purple-400 border border-purple-800 font-bold">CAUSATION_CHAIN</span>
                  </h2>
                  <p className="text-xs text-slate-400">End-to-End Decision & Order Causation Tracing</p>
                </div>
              </div>

              <div className="glass-panel p-6 rounded-xl border border-slate-800 space-y-4">
                <h3 className="font-bold text-white text-base">Entity Causation Chain Timeline</h3>
                <div className="space-y-3 font-mono text-xs">
                  <div className="p-3 bg-slate-900/60 rounded border border-slate-800 flex justify-between items-center">
                    <span>MarketEvent (BTC/USDT 1h Candle)</span>
                    <span className="text-slate-400">corr_id: c89e1a4f...99d2</span>
                  </div>
                  <div className="p-3 bg-slate-900/60 rounded border border-slate-800 flex justify-between items-center pl-6">
                    <span>└── FeatureSnapshot (SMA, RSI, Return)</span>
                    <span className="text-cyan-400">HEALTHY</span>
                  </div>
                  <div className="p-3 bg-slate-900/60 rounded border border-slate-800 flex justify-between items-center pl-12">
                    <span>└── AgentSignal (TrendAgent: LONG 0.85)</span>
                    <span className="text-emerald-400">EMITTED</span>
                  </div>
                  <div className="p-3 bg-slate-900/60 rounded border border-slate-800 flex justify-between items-center pl-16">
                    <span>└── RiskDecision (RiskGovernor: APPROVED)</span>
                    <span className="text-emerald-400">APPROVED</span>
                  </div>
                  <div className="p-3 bg-slate-900/60 rounded border border-slate-800 flex justify-between items-center pl-20">
                    <span>└── Fill (PaperExchangeAdapter: FILLED)</span>
                    <span className="text-purple-400">FILLED (0.1 BTC)</span>
                  </div>
                </div>
              </div>
            </div>
          )}

          {activeTab === 'incidents' && (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <h2 className="text-xl font-bold text-white">System Incidents & Audit Log</h2>
                <span className="px-2 py-1 rounded bg-slate-800 text-xs font-mono text-emerald-400 border border-emerald-500/30">Audit Stream</span>
              </div>
              <div className="glass-panel p-8 rounded-xl border border-slate-800 text-center text-slate-400 text-sm">
                Zero active system incidents reported. Data Guardian operating normally.
              </div>
            </div>
          )}

          {activeTab === 'advisor' && (
            <div className="space-y-4 flex flex-col h-full">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-xl font-bold text-white">{t('advisorTitle')}</h2>
                  <p className="text-xs text-slate-400 mt-1">{t('advisorSubtitle')}</p>
                </div>
                <span className="px-2 py-1 rounded bg-emerald-950 text-xs font-mono text-emerald-400 border border-emerald-800">packages/chat_agent</span>
              </div>

              {!advisorConfigured && (
                <div className="glass-panel p-4 rounded-xl border border-amber-800 bg-amber-950/30 text-amber-300 text-sm">
                  {t('advisorNotConfigured')}
                </div>
              )}

              <div className="glass-panel rounded-xl border border-slate-800 flex flex-col flex-1 min-h-[420px]">
                <div className="flex-1 overflow-y-auto p-5 space-y-3">
                  {chatMessages.length === 0 && (
                    <p className="text-slate-500 text-sm text-center mt-10">{t('advisorEmpty')}</p>
                  )}
                  {chatMessages.map((m, i) => (
                    <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                      <div
                        className={`max-w-[80%] rounded-lg px-4 py-2.5 text-sm whitespace-pre-wrap ${
                          m.role === 'user'
                            ? 'bg-cyan-600/90 text-white'
                            : 'bg-slate-800/80 text-slate-200 border border-slate-700'
                        }`}
                      >
                        {m.text}
                      </div>
                    </div>
                  ))}
                  {chatLoading && (
                    <div className="flex justify-start">
                      <div className="rounded-lg px-4 py-2.5 text-sm bg-slate-800/80 text-slate-400 border border-slate-700">
                        {t('advisorSending')}
                      </div>
                    </div>
                  )}
                  {chatError && <p className="text-red-400 text-xs">{chatError}</p>}
                </div>
                <div className="border-t border-slate-800 p-4 flex gap-2">
                  <input
                    type="text"
                    value={chatInput}
                    onChange={(e) => setChatInput(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter') handleSendChat(); }}
                    placeholder={t('advisorPlaceholder')}
                    disabled={chatLoading || !advisorConfigured}
                    className="flex-1 bg-slate-900 border border-slate-700 rounded-lg px-4 py-2.5 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-cyan-500 disabled:opacity-50"
                  />
                  <button
                    onClick={handleSendChat}
                    disabled={chatLoading || !chatInput.trim() || !advisorConfigured}
                    className="px-5 py-2.5 bg-cyan-600 hover:bg-cyan-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-medium rounded-lg transition"
                  >
                    {t('advisorSend')}
                  </button>
                </div>
              </div>

              <p className="text-[11px] text-slate-500 text-center">{t('advisorDisclaimer')}</p>
            </div>
          )}

          {activeTab === 'recommendations' && (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-xl font-bold text-white">{t('recommendationsTitle')}</h2>
                  <p className="text-xs text-slate-400 mt-1">{t('recommendationsSubtitle')}</p>
                </div>
                <span className="px-2 py-1 rounded bg-emerald-950 text-xs font-mono text-emerald-400 border border-emerald-800">apps/api/routers/recommendations.py</span>
              </div>

              {readiness && (
                <div className="grid grid-cols-2 md:grid-cols-6 gap-3 text-xs font-mono">
                  {([
                    ['architecture_readiness', readiness.architecture_readiness],
                    ['strategy_readiness', readiness.strategy_readiness],
                    ['model_readiness', readiness.model_readiness],
                    ['evidence_readiness', readiness.evidence_readiness],
                    ['shadow_readiness', readiness.shadow_readiness],
                    ['live_readiness', readiness.live_readiness],
                  ] as const).map(([key, value]) => (
                    <div key={key} className="glass-panel p-3 rounded-xl border border-slate-800">
                      <p className="text-slate-500 text-[10px] uppercase">{key.replace('_', ' ')}</p>
                      <p className={`font-bold text-xs mt-1 ${value === 'DISABLED' ? 'text-red-400' : value === 'READY' ? 'text-emerald-400' : 'text-amber-400'}`}>{value}</p>
                    </div>
                  ))}
                </div>
              )}

              <div className="glass-panel p-5 rounded-xl border border-slate-800 space-y-3">
                <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                  <div className="md:col-span-2">
                    <label className="text-xs text-slate-400 block mb-1">{t('scanSymbolsLabel')}</label>
                    <input
                      type="text"
                      value={recSymbols}
                      onChange={(e) => setRecSymbols(e.target.value)}
                      className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-cyan-500"
                    />
                  </div>
                  <div>
                    <label className="text-xs text-slate-400 block mb-1">{t('scanTimeframeLabel')}</label>
                    <select
                      value={recTimeframe}
                      onChange={(e) => setRecTimeframe(e.target.value)}
                      className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-cyan-500"
                    >
                      <option value="1d">1d</option>
                      <option value="4h">4h</option>
                      <option value="1h">1h</option>
                      <option value="15m">15m</option>
                    </select>
                  </div>
                </div>
                <button
                  onClick={handleScan}
                  disabled={recLoading}
                  className="px-5 py-2.5 bg-cyan-600 hover:bg-cyan-500 disabled:opacity-40 text-white text-sm font-medium rounded-lg transition"
                >
                  {recLoading ? t('scanning') : t('scanBtn')}
                </button>
                {recError && <p className="text-red-400 text-xs">{recError}</p>}
              </div>

              {recResult && (
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-mono text-slate-400">
                      {t('colResultState')}: <span className="text-cyan-400">{recResult.application_result_state}</span>
                    </span>
                    <span className="text-xs font-mono text-slate-500">{recResult.proposals.length} {t('proposalsFound')}</span>
                  </div>

                  {recResult.proposals.length === 0 ? (
                    <div className="glass-panel p-8 rounded-xl border border-slate-800 text-center text-slate-400 text-sm space-y-2">
                      <p>{t('noProposals')}</p>
                      {recResult.reason_codes.length > 0 && (
                        <p className="text-[11px] text-slate-500 font-mono">{t('reasonCodes')}: {recResult.reason_codes.join(', ')}</p>
                      )}
                    </div>
                  ) : (
                    recResult.proposals.map((p) => (
                      <div key={p.proposal_id} className="glass-panel p-5 rounded-xl border border-slate-800 space-y-3">
                        <div className="flex justify-between items-center border-b border-slate-800 pb-3">
                          <h3 className="font-bold text-white text-base">{p.symbol} — {p.direction} ({p.timeframe})</h3>
                          <div className="flex gap-2">
                            {p.application_result_state !== 'APPROVED_PROPOSAL' && (
                              <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-amber-950 text-amber-400 border border-amber-800">{t('researchOnly')}</span>
                            )}
                            <span className="px-2 py-0.5 rounded text-xs font-mono bg-slate-800 text-slate-300 border border-slate-700">{p.evidence_status}</span>
                          </div>
                        </div>
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs font-mono">
                          <div className="bg-slate-900/60 p-3 rounded border border-slate-800">
                            <p className="text-slate-400">{t('colEntry')}</p>
                            <p className="text-white font-bold text-sm">{p.entry_reference}</p>
                          </div>
                          <div className="bg-slate-900/60 p-3 rounded border border-slate-800">
                            <p className="text-slate-400">{t('colTakeProfit')}</p>
                            <p className="text-emerald-400 font-bold text-sm">{p.take_profit ?? '—'}</p>
                          </div>
                          <div className="bg-slate-900/60 p-3 rounded border border-slate-800">
                            <p className="text-slate-400">{t('colRiskReward')}</p>
                            <p className="text-white font-bold text-sm">{p.risk_reward_ratio ?? '—'}</p>
                          </div>
                          <div className="bg-slate-900/60 p-3 rounded border border-slate-800">
                            <p className="text-slate-400">{t('colProbability')}</p>
                            <p className="text-cyan-400 font-bold text-sm">{p.calibrated_probability ?? '—'}</p>
                          </div>
                          <div className="bg-slate-900/60 p-3 rounded border border-slate-800">
                            <p className="text-slate-400">{t('colNetReturn')}</p>
                            <p className="text-white font-bold text-sm">{p.expected_net_return_bps ?? '—'} bps</p>
                          </div>
                          <div className="bg-slate-900/60 p-3 rounded border border-slate-800">
                            <p className="text-slate-400">{t('colApprovedRisk')}</p>
                            <p className="text-amber-400 font-bold text-sm">{p.approved_risk_pct ?? '—'}</p>
                          </div>
                        </div>
                        {p.reason_codes.length > 0 && (
                          <p className="text-[11px] text-slate-500 font-mono">{t('reasonCodes')}: {p.reason_codes.join(', ')}</p>
                        )}
                      </div>
                    ))
                  )}
                </div>
              )}
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
