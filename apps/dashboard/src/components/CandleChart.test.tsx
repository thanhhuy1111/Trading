// @vitest-environment jsdom

import '@testing-library/jest-dom/vitest';
import { cleanup, render, screen } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import CandleChart from './CandleChart';

vi.mock('recharts', () => ({
  Bar: () => null,
  CartesianGrid: () => null,
  ComposedChart: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  Line: () => null,
  ResponsiveContainer: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  Tooltip: () => null,
  XAxis: () => null,
  YAxis: () => null,
}));

describe('CandleChart responsive controls', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const body = String(input).includes('trend-projection')
        ? { available: false, points: [] }
        : [];
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }));
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('stacks the toolbar and scrolls timeframe buttons on narrow screens', () => {
    render(
      <CandleChart
        lang="en"
        symbol="BTCUSDT"
        timeframe="4h"
        onSymbolChange={vi.fn()}
        onTimeframeChange={vi.fn()}
      />,
    );

    expect(screen.getByTestId('chart-toolbar')).toHaveClass('flex-col', 'sm:flex-row');
    expect(screen.getByTestId('timeframe-strip')).toHaveClass('overflow-x-auto', 'w-full');
    for (const label of ['1m', '5m', '15m', '1h', '4h', '1d']) {
      expect(screen.getByRole('button', { name: label })).toHaveClass('shrink-0');
    }
  });
});
