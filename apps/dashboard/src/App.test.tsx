// @vitest-environment jsdom

import '@testing-library/jest-dom/vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import App from './App';

vi.mock('./components/CandleChart', () => ({
  default: ({
    onSymbolChange,
    onTimeframeChange,
  }: {
    onSymbolChange: (symbol: string) => void;
    onTimeframeChange: (timeframe: string) => void;
  }) => (
    <div>
      Candle chart
      <button onClick={() => onSymbolChange('ETHUSDT')}>Select ETH</button>
      <button onClick={() => onTimeframeChange('1h')}>Select 1h</button>
    </div>
  ),
}));
vi.mock('./components/ChatPanel', () => ({ default: () => <div>Chat panel</div> }));

const analysis = {
  analysis_id: 'ui-test',
  symbol: 'BTC/USDT',
  timeframe: '4h',
  recommendation: 'NO_DECISION',
  status: 'AVAILABLE',
  as_of_time: '2026-07-24T07:59:59.999Z',
  agents: [
    {
      agent_name: 'regime_agent_v1',
      status: 'AVAILABLE',
      regime: 'SIDEWAYS',
      heuristic_score: '0.5',
      reason_codes: ['NO_STRONG_TREND_OR_VOLATILITY_SIGNAL'],
    },
    {
      agent_name: 'reversion_agent_v1',
      status: 'AVAILABLE',
      action: 'NO_SIGNAL',
      heuristic_score: '0.5',
      reason_codes: ['INSIDE_NEUTRAL_ZONE'],
    },
    { agent_name: 'quantitative_agent', status: 'UNAVAILABLE', reason_codes: ['QUANTITATIVE_RUNTIME_NOT_BOUND'] },
  ],
  debate: { status: 'NOT_RUN', reason_codes: ['GEMINI_NOT_CONFIGURED'], turns: [] },
  evidence: [{ evidence_id: 'ui-test:technical:rsi_14', name: 'rsi_14', numeric_value: '50' }],
  verification: { decision: 'NOT_RUN' },
  risk: { allow_trade: false, approved_quantity: '0' },
};

describe('campaign dashboard', () => {
  beforeEach(() => {
    vi.stubGlobal('localStorage', {
      getItem: vi.fn(() => 'en'),
      setItem: vi.fn(),
    });
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const body = url.includes('/system/health')
        ? { analysis_runtime: 'RESEARCH_ONLY' }
        : url.includes('/predictions')
          ? { status: 'UNAVAILABLE', items: [] }
          : analysis;
      return new Response(JSON.stringify(body), {
        status: url.includes('/analysis/run') ? 202 : 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }));
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('renders a completed research analysis without implying trade authority', async () => {
    render(<App />);
    expect(screen.getByText(/No analysis yet/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText(/Runtime: RESEARCH_ONLY/)).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: 'Run analysis' }));
    await waitFor(() => expect(screen.getByText('regime_agent_v1')).toBeInTheDocument());
    expect(screen.getByText('reversion_agent_v1')).toBeInTheDocument();
    expect(screen.getByText('quantitative_agent')).toBeInTheDocument();
    expect(screen.getByText(/"decision": "NOT_RUN"/)).toBeInTheDocument();
    expect(screen.getByText(/"allow_trade": false/)).toBeInTheDocument();
    expect(screen.getByText(/1 evidence records/)).toBeInTheDocument();
    expect(screen.getByText(/0 predictions · UNAVAILABLE/)).toBeInTheDocument();
    expect(screen.getByText(/Analysis context: BTC\/USDT · 4h/)).toBeInTheDocument();
    expect(screen.queryByText('[object Object]')).not.toBeInTheDocument();
  });

  it('clears a completed analysis when its market scope changes', async () => {
    render(<App />);
    fireEvent.click(screen.getByRole('button', { name: 'Run analysis' }));
    await waitFor(() => expect(screen.getByText('regime_agent_v1')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: 'Select ETH' }));
    expect(screen.queryByText('regime_agent_v1')).not.toBeInTheDocument();
    expect(screen.getByText(/No analysis yet/)).toBeInTheDocument();
    expect(screen.getByText(/ETH\/USDT · 4h/)).toBeInTheDocument();
  });

  it('aborts and ignores a late response after the market scope changes', async () => {
    let resolveAnalysis: ((response: Response) => void) | undefined;
    let analysisSignal: AbortSignal | undefined;
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes('/analysis/run')) {
        analysisSignal = init?.signal ?? undefined;
        return new Promise<Response>((resolve) => {
          resolveAnalysis = resolve;
        });
      }
      const body = url.includes('/system/health')
        ? { analysis_runtime: 'RESEARCH_ONLY' }
        : { status: 'UNAVAILABLE', items: [] };
      return Promise.resolve(new Response(JSON.stringify(body), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }));
    }));

    render(<App />);
    fireEvent.click(screen.getByRole('button', { name: 'Run analysis' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Running…' })).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: 'Select ETH' }));
    expect(analysisSignal?.aborted).toBe(true);
    await act(async () => {
      resolveAnalysis?.(new Response(JSON.stringify(analysis), {
        status: 202,
        headers: { 'Content-Type': 'application/json' },
      }));
    });
    expect(screen.queryByText('regime_agent_v1')).not.toBeInTheDocument();
    expect(screen.getByText(/No analysis yet/)).toBeInTheDocument();
  });
});
