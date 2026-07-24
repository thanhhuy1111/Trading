import { useEffect, useRef, useState } from 'react';
import CandleChart from './components/CandleChart';
import ChatPanel from './components/ChatPanel';
import { analysisState, itemCount } from './analysisView';
import { useTranslation, type Lang } from './i18n';

export default function App() {
  const [lang, setLang] = useState<Lang>(() => (localStorage.getItem('lang') as Lang) || 'vi');
  const t = useTranslation(lang);
  const toggleLang = () => {
    const next: Lang = lang === 'en' ? 'vi' : 'en';
    setLang(next);
    localStorage.setItem('lang', next);
  };

  const [isBackendAvailable, setIsBackendAvailable] = useState(false);
  const [analysis, setAnalysis] = useState<Record<string, unknown> | null>(null);
  const [analysisError, setAnalysisError] = useState('');
  const [isRunning, setIsRunning] = useState(false);
  const [systemHealth, setSystemHealth] = useState<Record<string, unknown> | null>(null);
  const [predictions, setPredictions] = useState<Record<string, unknown> | null>(null);
  const [symbol, setSymbol] = useState('BTCUSDT');
  const [timeframe, setTimeframe] = useState('4h');
  const activeAnalysisRequest = useRef(0);
  const analysisAbortController = useRef<AbortController | null>(null);
  const clearAnalysisForScopeChange = () => {
    activeAnalysisRequest.current += 1;
    analysisAbortController.current?.abort();
    analysisAbortController.current = null;
    setIsRunning(false);
    setAnalysis(null);
    setAnalysisError('');
  };
  const changeSymbol = (nextSymbol: string) => {
    clearAnalysisForScopeChange();
    setSymbol(nextSymbol);
  };
  const changeTimeframe = (nextTimeframe: string) => {
    clearAnalysisForScopeChange();
    setTimeframe(nextTimeframe);
  };

  const runAnalysis = async () => {
    analysisAbortController.current?.abort();
    const controller = new AbortController();
    analysisAbortController.current = controller;
    const requestVersion = activeAnalysisRequest.current + 1;
    activeAnalysisRequest.current = requestVersion;
    const requestedSymbol = symbol === 'BTCUSDT' ? 'BTC/USDT' : 'ETH/USDT';
    const requestedTimeframe = timeframe;
    setIsRunning(true);
    setAnalysisError('');
    try {
      const response = await fetch('/api/v1/analysis/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: controller.signal,
        body: JSON.stringify({
          symbol: requestedSymbol,
          timeframe: requestedTimeframe,
        }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body?.message || 'Analysis request failed');
      if (activeAnalysisRequest.current === requestVersion) {
        setAnalysis(body);
      }
    } catch (error) {
      if (
        activeAnalysisRequest.current === requestVersion
        && !(error instanceof DOMException && error.name === 'AbortError')
      ) {
        setAnalysisError(error instanceof Error ? error.message : 'Analysis request failed');
      }
    } finally {
      if (activeAnalysisRequest.current === requestVersion) {
        analysisAbortController.current = null;
        setIsRunning(false);
      }
    }
  };

  useEffect(() => {
    const checkBackend = async () => {
      try {
        const res = await fetch('/api/v1/system/health');
        if (res.ok) setSystemHealth(await res.json());
        setIsBackendAvailable(res.ok);
      } catch {
        setIsBackendAvailable(false);
      }
    };
    const loadPredictions = async () => {
      try {
        const response = await fetch('/api/v1/predictions');
        if (response.ok) setPredictions(await response.json());
      } catch {
        setPredictions(null);
      }
    };
    checkBackend();
    loadPredictions();
    const interval = setInterval(checkBackend, 10000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="min-h-screen xl:h-screen flex flex-col bg-slate-950 text-slate-100 xl:overflow-hidden">
      <header className="flex items-center justify-between px-5 py-3 border-b border-white/[0.06] shrink-0">
        <div className="flex items-center gap-2.5">
          <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-cyan-500 to-blue-600 flex items-center justify-center text-[11px] font-bold text-white">
            AG
          </div>
          <span className="text-sm font-semibold text-slate-200">{t('appTitle')}</span>
        </div>
        <div className="flex items-center gap-3">
          <span
            className={`flex items-center gap-1.5 text-[11px] font-medium px-2.5 py-1 rounded-full ${
              isBackendAvailable ? 'text-emerald-400 bg-emerald-500/10' : 'text-red-400 bg-red-500/10'
            }`}
          >
            <span className={`w-1.5 h-1.5 rounded-full ${isBackendAvailable ? 'bg-emerald-400' : 'bg-red-400'}`} />
            {isBackendAvailable ? t('apiOnline') : t('apiUnavailable')}
          </span>
          <button
            onClick={toggleLang}
            className="text-[11px] text-slate-500 hover:text-slate-300 px-2 py-1 rounded transition"
          >
            {lang === 'en' ? 'Tiếng Việt' : 'English'}
          </button>
        </div>
      </header>

      <main className="flex-1 grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_380px] xl:min-h-0 xl:overflow-hidden">
        <div className="min-w-0 flex flex-col xl:min-h-0">
          <section className="px-5 py-4 border-b border-white/[0.06]">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="text-[11px] uppercase tracking-[0.2em] text-cyan-400">
                  {symbol === 'BTCUSDT' ? 'BTC/USDT' : 'ETH/USDT'} · {timeframe}
                </p>
                <h1 className="text-xl font-semibold mt-1">Evidence-first analysis</h1>
              </div>
              <button
                onClick={runAnalysis}
                disabled={isRunning}
                className="rounded-lg bg-cyan-500 px-4 py-2 text-sm font-semibold text-slate-950 disabled:opacity-50"
              >
                {isRunning ? 'Running…' : 'Run analysis'}
              </button>
            </div>
            {analysisError && <p role="alert" className="mt-3 text-sm text-red-400">{analysisError}</p>}
            {!analysis && !analysisError && (
              <p className="mt-3 text-sm text-slate-500">No analysis yet. Run one to inspect agents, evidence, verification and risk.</p>
            )}
            {analysis && (
              <div className="mt-4 grid grid-cols-2 lg:grid-cols-3 gap-2">
                {['recommendation', 'status'].map((key) => (
                  <div key={key} className="rounded-lg border border-white/[0.07] bg-white/[0.03] p-3">
                    <p className="text-[10px] uppercase text-slate-500">{key}</p>
                    <p className="mt-1 text-sm text-slate-200">
                      {String(analysis[key] ?? 'Empty')}
                    </p>
                  </div>
                ))}
                <div className="rounded-lg border border-white/[0.07] bg-white/[0.03] p-3">
                  <p className="text-[10px] uppercase text-slate-500">state</p>
                  <p className="mt-1 text-sm text-slate-200">{analysisState(analysis)}</p>
                </div>
                {analysis.as_of_time != null && (
                  <div className="col-span-2 lg:col-span-3 text-[11px] text-slate-500">
                    Analysis context: {String(analysis.symbol)} · {String(analysis.timeframe)}
                    {' · '}Point-in-time snapshot: {new Date(String(analysis.as_of_time)).toLocaleString()}
                  </div>
                )}
              </div>
            )}
            <div className="mt-4 grid gap-3 lg:grid-cols-2">
              <section aria-label="Agent Inspector" className="rounded-lg border border-white/[0.07] bg-white/[0.02] p-3">
                <h2 className="text-sm font-semibold">Agent Inspector</h2>
                {analysis && Array.isArray(analysis.agents) && analysis.agents.length ? (
                  <ul className="mt-2 space-y-2 text-xs text-slate-400">
                    {(analysis.agents as Record<string, unknown>[]).map((agent) => (
                      <li key={String(agent.agent_name)} className="rounded bg-black/20 p-2">
                        <span className="text-slate-200">{String(agent.agent_name)}</span>
                        {' · '}{String(agent.status)}
                        {agent.regime ? <div>regime: {String(agent.regime)}</div> : null}
                        {agent.action ? <div>action: {String(agent.action)}</div> : null}
                        {agent.heuristic_score ? (
                          <div>heuristic score: {String(agent.heuristic_score)}</div>
                        ) : null}
                        <div>{Array.isArray(agent.reason_codes) ? agent.reason_codes.join(', ') : ''}</div>
                      </li>
                    ))}
                  </ul>
                ) : <p className="mt-2 text-xs text-slate-500">No agent output</p>}
              </section>
              <section aria-label="Evidence Viewer" className="rounded-lg border border-white/[0.07] bg-white/[0.02] p-3">
                <h2 className="text-sm font-semibold">Evidence Viewer</h2>
                <p className="mt-2 text-xs text-slate-500">
                  {analysis ? `${itemCount(analysis.evidence)} evidence records` : 'No evidence'}
                </p>
                {analysis && itemCount(analysis.evidence) > 0 && (
                  <pre className="mt-2 max-h-64 overflow-auto text-[10px]">{JSON.stringify(analysis.evidence, null, 2)}</pre>
                )}
              </section>
              <section aria-label="Verification and Risk" className="rounded-lg border border-white/[0.07] bg-white/[0.02] p-3">
                <h2 className="text-sm font-semibold">Verification &amp; Risk</h2>
                <pre className="mt-2 overflow-auto text-[10px] text-slate-400">
                  {analysis ? JSON.stringify({ verification: analysis.verification, risk: analysis.risk }, null, 2) : 'No decision'}
                </pre>
              </section>
              <section aria-label="Debate Transcript" className="rounded-lg border border-white/[0.07] bg-white/[0.02] p-3">
                <h2 className="text-sm font-semibold">Debate Transcript</h2>
                <pre className="mt-2 overflow-auto text-[10px] text-slate-400">
                  {analysis ? JSON.stringify(analysis.debate ?? null, null, 2) : 'No debate'}
                </pre>
              </section>
              <section aria-label="Prediction History" className="rounded-lg border border-white/[0.07] bg-white/[0.02] p-3">
                <h2 className="text-sm font-semibold">Prediction History</h2>
                <p className="mt-2 text-xs text-slate-500">
                  {predictions ? `${itemCount(predictions.items)} predictions · ${String(predictions.status)}` : 'Prediction history unavailable'}
                </p>
              </section>
              <section aria-label="System Health" className="rounded-lg border border-white/[0.07] bg-white/[0.02] p-3">
                <h2 className="text-sm font-semibold">System Health</h2>
                <p className="mt-2 text-xs text-slate-500">
                  {systemHealth ? `Runtime: ${String(systemHealth.analysis_runtime ?? 'unknown')}` : 'Health unavailable'}
                </p>
              </section>
            </div>
          </section>
          <div className="flex-1 min-h-[420px]">
            <CandleChart
              lang={lang}
              symbol={symbol}
              timeframe={timeframe}
              onSymbolChange={changeSymbol}
              onTimeframeChange={changeTimeframe}
            />
          </div>
        </div>
        <div className="shrink-0 border-t xl:border-t-0 xl:border-l border-white/[0.06] min-h-[420px] xl:min-h-0">
          <ChatPanel lang={lang} />
        </div>
      </main>
    </div>
  );
}
