// @vitest-environment jsdom

import '@testing-library/jest-dom/vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import App from './App';

vi.mock('./components/CandleChart', () => ({ default: () => <div>Candle chart</div> }));
vi.mock('./components/ChatPanel', () => ({ default: () => <div>Chat panel</div> }));

const analysis = {
  analysis_id: 'ui-test',
  recommendation: 'NO_DECISION',
  status: 'UNAVAILABLE',
  agents: [
    { agent_name: 'technical_agent', status: 'UNAVAILABLE', reason_codes: ['NOT_CONFIGURED'] },
    { agent_name: 'derivatives_agent', status: 'UNAVAILABLE', reason_codes: ['NOT_CONFIGURED'] },
    { agent_name: 'quantitative_agent', status: 'UNAVAILABLE', reason_codes: ['NOT_CONFIGURED'] },
  ],
  debate: { status: 'FAILED', turns: [] },
  evidence: [],
  verification: { decision: 'REJECTED' },
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
        ? { analysis_runtime: 'UNAVAILABLE' }
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
    vi.unstubAllGlobals();
  });

  it('renders empty and health states, then inspectable safe rejection', async () => {
    render(<App />);
    expect(screen.getByText(/No analysis yet/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText(/Runtime: UNAVAILABLE/)).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: 'Run analysis' }));
    await waitFor(() => expect(screen.getByText('technical_agent')).toBeInTheDocument());
    expect(screen.getByText('derivatives_agent')).toBeInTheDocument();
    expect(screen.getByText('quantitative_agent')).toBeInTheDocument();
    expect(screen.getByText(/"decision": "REJECTED"/)).toBeInTheDocument();
    expect(screen.getByText(/"allow_trade": false/)).toBeInTheDocument();
    expect(screen.getByText(/0 predictions · UNAVAILABLE/)).toBeInTheDocument();
    expect(screen.queryByText('[object Object]')).not.toBeInTheDocument();
  });
});
