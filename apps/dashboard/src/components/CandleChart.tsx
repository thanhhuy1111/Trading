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
}

interface TrendProjectionPoint {
  time: string;
  projected_price: string;
}

interface TrendProjectionResponse {
  available: boolean;
  reason?: string;
  basis?: string;
  slope?: string;
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
}

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
  const bodyX = x + width * 0.2;
  const bodyWidth = width * 0.6;
  return (
    <g>
      <line x1={wickX} y1={y} x2={wickX} y2={y + height} stroke={color} strokeWidth={1} />
      <rect x={bodyX} y={bodyY} width={bodyWidth} height={bodyHeight} fill={color} />
    </g>
  );
}

export default function CandleChart({ symbol, timeframe, lang }: { symbol: string; timeframe: string; lang: Lang }) {
  const t = useTranslation(lang);
  const [rows, setRows] = useState<ChartRow[]>([]);
  const [projection, setProjection] = useState<TrendProjectionResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

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

        const candleRows: ChartRow[] = rawCandles.map((c) => {
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

  return (
    <div className="glass-panel p-4 rounded-xl border border-slate-800 space-y-2">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-300">{t('chartTitle')}: {symbol} ({timeframe})</h3>
        {loading && <span className="text-xs text-slate-500">...</span>}
      </div>

      {error ? (
        <div className="h-80 flex items-center justify-center text-sm text-red-400">{error}</div>
      ) : rows.length === 0 ? (
        <div className="h-80 flex items-center justify-center text-sm text-slate-500">
          {loading ? t('chartLoading') : t('chartNoData')}
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={320}>
          <ComposedChart data={rows} margin={{ top: 5, right: 10, bottom: 5, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis
              dataKey="timeLabel" tick={{ fontSize: 10, fill: '#64748b' }}
              tickFormatter={(v: string) => v.split(',')[1]?.trim() || v}
              minTickGap={40}
            />
            <YAxis domain={['auto', 'auto']} tick={{ fontSize: 10, fill: '#64748b' }} width={70} />
            <Tooltip
              contentStyle={{ background: '#0f172a', border: '1px solid #1e293b', fontSize: 12 }}
              labelFormatter={(v: string) => v}
            />
            <Bar dataKey="range" shape={CandlestickShape} isAnimationActive={false} />
            <Line
              type="linear" dataKey="projected" stroke="#f59e0b" strokeWidth={2} strokeDasharray="5 4"
              dot={false} isAnimationActive={false} connectNulls
            />
          </ComposedChart>
        </ResponsiveContainer>
      )}

      <p className="text-[11px] text-slate-500">
        {projection?.available
          ? `${t('chartProjectionLabel')} (slope: ${projection.slope})`
          : t('chartProjectionUnavailable')}
      </p>
    </div>
  );
}
