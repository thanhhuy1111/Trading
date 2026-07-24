import { useEffect, useState } from 'react';
import { Bar, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { useTranslation, type Lang } from '../i18n';

interface RawCandle {
  open_time: string;
  close_time: string;
  open_price: string;
  high_price: string;
  low_price: string;
  close_price: string;
  volume: string;
  is_closed: boolean;
}

interface TrendProjectionPoint {
  time: string;
  projected_price: string;
  horizon_bars: number;
  oos_mape: number;
  oos_directional_accuracy: number;
}

interface TrendProjectionResponse {
  available: boolean;
  reason?: string;
  basis?: string;
  model_status?: 'NO_TRAINED_MODEL' | 'NO_APPROVED_MODEL' | 'PARTIAL' | 'FULLY_APPROVED';
  model_trained_at?: string;
  points: TrendProjectionPoint[];
}

// One row per point on the chart. Real candles carry open/high/low/close; projection-only
// rows carry only `projected` (and the seam row -- the last real candle -- carries both, so
// the dashed projection line visually starts exactly at the last real close, never floating
// disconnected from it).
interface ChartRow {
  time: number;
  timeLabel: string;
  open?: number;
  high?: number;
  low?: number;
  close?: number;
  range?: [number, number];
  projected?: number;
  oosMape?: number;
  oosDirAcc?: number;
}

const SYMBOLS = ['BTCUSDT', 'ETHUSDT'];
const TIMEFRAMES = ['1m', '5m', '15m', '1h', '4h', '1d'];

function CandlestickShape(props: any) {
  const { x, y, width, height, payload } = props;
  if (payload.open === undefined || payload.close === undefined) return <g />;
  const isBullish = payload.close >= payload.open;
  const color = isBullish ? '#10b981' : '#f43f5e';
  const range = payload.high - payload.low;
  if (range <= 0) return <g />;
  const pxPerUnit = height / range;
  const bodyTopPrice = Math.max(payload.open, payload.close);
  const bodyBottomPrice = Math.min(payload.open, payload.close);
  const bodyY = y + (payload.high - bodyTopPrice) * pxPerUnit;
  const bodyHeight = Math.max(1, (bodyTopPrice - bodyBottomPrice) * pxPerUnit);
  const wickX = x + width / 2;
  const bodyX = x + width * 0.22;
  const bodyWidth = width * 0.56;
  return (
    <g>
      <line x1={wickX} y1={y} x2={wickX} y2={y + height} stroke={color} strokeWidth={1.5} />
      <rect x={bodyX} y={bodyY} width={Math.max(1, bodyWidth)} height={bodyHeight} fill={color} />
    </g>
  );
}

function ChartTooltip({ active, payload, t }: any) {
  if (!active || !payload || payload.length === 0) return null;
  const row: ChartRow = payload[0].payload;
  if (row.open !== undefined) {
    const isBullish = (row.close ?? 0) >= row.open;
    return (
      <div className="rounded-lg border border-white/10 bg-slate-950/95 px-3 py-2 text-[11px] shadow-xl">
        <p className="text-slate-500 mb-1">{row.timeLabel}</p>
        <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 font-mono">
          <span className="text-slate-500">O</span><span className="text-slate-300">{row.open?.toFixed(2)}</span>
          <span className="text-slate-500">H</span><span className="text-slate-300">{row.high?.toFixed(2)}</span>
          <span className="text-slate-500">L</span><span className="text-slate-300">{row.low?.toFixed(2)}</span>
          <span className="text-slate-500">C</span>
          <span className={isBullish ? 'text-emerald-400' : 'text-rose-400'}>{row.close?.toFixed(2)}</span>
        </div>
      </div>
    );
  }
  if (row.projected !== undefined) {
    return (
      <div className="rounded-lg border border-white/10 bg-slate-950/95 px-3 py-2 text-[11px] shadow-xl">
        <p className="text-slate-500 mb-1">{row.timeLabel}</p>
        <p className="text-amber-400 font-mono">{row.projected.toFixed(2)}</p>
        {row.oosMape !== undefined && (
          <p className="text-slate-500 font-mono mt-1">
            {t('chartOosMape')} {(row.oosMape * 100).toFixed(2)}% · {(row.oosDirAcc! * 100).toFixed(1)}% {t('chartOosDirAcc')}
          </p>
        )}
      </div>
    );
  }
  return null;
}

interface CandleChartProps {
  lang: Lang;
  symbol: string;
  timeframe: string;
  onSymbolChange: (symbol: string) => void;
  onTimeframeChange: (timeframe: string) => void;
  disabled?: boolean;
}

export default function CandleChart({
  lang,
  symbol,
  timeframe,
  onSymbolChange,
  onTimeframeChange,
  disabled = false,
}: CandleChartProps) {
  const t = useTranslation(lang);
  const [rows, setRows] = useState<ChartRow[]>([]);
  const [projection, setProjection] = useState<TrendProjectionResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setRows([]);
    setProjection(null);
    setError(null);
    setLoading(true);

    const load = async () => {
      try {
        const [candlesRes, projectionRes] = await Promise.all([
          fetch(`/api/market-data/candles?symbol=${encodeURIComponent(symbol)}&timeframe=${timeframe}&limit=80`),
          fetch(`/api/market-data/trend-projection?symbol=${encodeURIComponent(symbol)}&timeframe=${timeframe}&projection_bars=12`),
        ]);
        if (!candlesRes.ok) {
          if (!cancelled) setError(t('chartLoadError'));
          return;
        }
        const rawCandles: RawCandle[] = await candlesRes.json();
        const projectionData: TrendProjectionResponse = projectionRes.ok
          ? await projectionRes.json()
          : { available: false, points: [] };

        const candleRows: ChartRow[] = rawCandles.filter((c) => c.is_closed).map((c) => {
          const time = new Date(c.close_time).getTime();
          const open = parseFloat(c.open_price);
          const high = parseFloat(c.high_price);
          const low = parseFloat(c.low_price);
          const close = parseFloat(c.close_price);
          return {
            time, timeLabel: new Date(time).toLocaleString(),
            open, high, low, close, range: [low, high],
          };
        });

        if (candleRows.length > 0 && projectionData.available) {
          // Seam row: attach the projection's starting value to the last real candle so the
          // dashed line is visually continuous with the real close, not a floating segment.
          candleRows[candleRows.length - 1].projected = candleRows[candleRows.length - 1].close;
          for (const p of projectionData.points) {
            candleRows.push({
              time: new Date(p.time).getTime(),
              timeLabel: new Date(p.time).toLocaleString(),
              projected: parseFloat(p.projected_price),
              oosMape: p.oos_mape,
              oosDirAcc: p.oos_directional_accuracy,
            });
          }
        }

        if (!cancelled) {
          setRows(candleRows);
          setProjection(projectionData);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) setError(t('chartLoadError'));
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    load();
    const interval = setInterval(load, 15000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [symbol, timeframe, lang]);

  const lastClose = rows.length > 0 ? [...rows].reverse().find((r) => r.close !== undefined)?.close : undefined;
  const firstOpen = rows.find((r) => r.open !== undefined)?.open;
  const changePct = lastClose !== undefined && firstOpen ? ((lastClose - firstOpen) / firstOpen) * 100 : undefined;

  return (
    <div className="flex flex-col h-full">
      <div
        data-testid="chart-toolbar"
        className="flex flex-col gap-3 px-5 py-4 border-b border-white/[0.06] sm:flex-row sm:items-center sm:justify-between"
      >
        <div className="min-w-0 flex flex-wrap items-baseline gap-3">
          <h2 className="text-base font-semibold text-slate-100">{symbol}</h2>
          {lastClose !== undefined && (
            <span className="text-xl sm:text-2xl font-semibold tabular-nums text-slate-50">
              {lastClose.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </span>
          )}
          {changePct !== undefined && (
            <span className={`text-xs font-medium tabular-nums px-1.5 py-0.5 rounded ${changePct >= 0 ? 'text-emerald-400 bg-emerald-500/10' : 'text-rose-400 bg-rose-500/10'}`}>
              {changePct >= 0 ? '+' : ''}{changePct.toFixed(2)}%
            </span>
          )}
        </div>
        <div className="flex min-w-0 w-full flex-col gap-2 sm:w-auto sm:flex-row sm:items-center sm:gap-3">
          <select
            value={symbol}
            onChange={(e) => onSymbolChange(e.target.value)}
            disabled={disabled}
            className="w-full sm:w-auto bg-white/[0.04] border border-white/[0.08] rounded-lg px-2.5 py-1.5 text-xs text-slate-300 focus:outline-none focus:border-cyan-500/60"
          >
            {SYMBOLS.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <div
            data-testid="timeframe-strip"
            className="flex w-full sm:w-auto items-center gap-0.5 overflow-x-auto bg-white/[0.04] border border-white/[0.08] rounded-lg p-0.5"
          >
            {TIMEFRAMES.map((tf) => (
              <button
                key={tf}
                onClick={() => onTimeframeChange(tf)}
                disabled={disabled}
                className={`shrink-0 px-2.5 py-1 text-xs font-medium rounded-md transition ${
                  timeframe === tf ? 'bg-cyan-600 text-white' : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                {tf}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="flex-1 min-h-0 px-3 pt-3">
        {error ? (
          <div className="h-full flex items-center justify-center text-sm text-red-400">{error}</div>
        ) : rows.length === 0 ? (
          <div className="h-full flex items-center justify-center text-sm text-slate-600">
            {loading ? t('chartLoading') : t('chartNoData')}
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={rows} margin={{ top: 5, right: 8, bottom: 5, left: 0 }}>
              <CartesianGrid strokeDasharray="" stroke="rgba(255,255,255,0.05)" vertical={false} />
              <XAxis
                dataKey="timeLabel" tick={{ fontSize: 10, fill: '#475569' }}
                tickFormatter={(v: string) => v.split(',')[1]?.trim() || v}
                minTickGap={50} axisLine={{ stroke: 'rgba(255,255,255,0.06)' }} tickLine={false}
              />
              <YAxis
                domain={['auto', 'auto']} tick={{ fontSize: 10, fill: '#475569' }} width={64}
                orientation="right" axisLine={false} tickLine={false}
                tickFormatter={(v: number) => v.toLocaleString()}
              />
              <Tooltip content={<ChartTooltip t={t} />} />
              <Bar dataKey="range" shape={CandlestickShape} isAnimationActive={false} />
              <Line
                type="linear" dataKey="projected" stroke="#f59e0b" strokeWidth={2} strokeDasharray="5 4"
                dot={false} isAnimationActive={false} connectNulls
              />
            </ComposedChart>
          </ResponsiveContainer>
        )}
      </div>

      <p className="px-5 py-2.5 text-[11px] text-slate-600 border-t border-white/[0.06]">
        {projection?.available && projection.points.length > 0 ? (
          <>
            <span className="text-amber-500">{t('chartProjectionLabel')}</span>
            {' — '}
            {t('chartOosMape')} {(projection.points[0].oos_mape * 100).toFixed(2)}%,{' '}
            {(projection.points[0].oos_directional_accuracy * 100).toFixed(1)}% {t('chartOosDirAcc')}
            {` (h+${projection.points[0].horizon_bars})`}
          </>
        ) : projection?.model_status === 'NO_APPROVED_MODEL' ? (
          t('chartProjectionNotApproved')
        ) : (
          t('chartProjectionNoModel')
        )}
      </p>
    </div>
  );
}
