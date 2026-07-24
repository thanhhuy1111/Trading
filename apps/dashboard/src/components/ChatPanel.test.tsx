// @vitest-environment jsdom

import '@testing-library/jest-dom/vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import ChatPanel from './ChatPanel';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it('disables chat immediately when Gemini is not configured', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({
    status: 'NOT_CONFIGURED',
    reason_codes: ['GEMINI_NOT_CONFIGURED'],
  }), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })));

  render(<ChatPanel lang="en" />);

  await waitFor(() => expect(screen.getByText(/Gemini chat is unavailable/)).toBeInTheDocument());
  expect(screen.getByPlaceholderText(/Ask about market conditions/)).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled();
});

it('sends a chat turn only after configured health is confirmed', async () => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    if (String(input).endsWith('/chat/health')) {
      return new Response(JSON.stringify({ status: 'CONFIGURED' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }
    return new Response(JSON.stringify({
      conversation_id: 'conversation-test',
      message_id: 'message-test',
      answer: 'Grounded research response.',
      model: 'configured-model',
      prompt_version: 'v1',
      generated_at: '2026-07-24T00:00:00Z',
    }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  });
  vi.stubGlobal('fetch', fetchMock);

  render(<ChatPanel lang="en" />);

  const input = screen.getByPlaceholderText(/Ask about market conditions/);
  await waitFor(() => expect(input).toBeEnabled());
  fireEvent.change(input, { target: { value: 'Analyze BTC.' } });
  fireEvent.click(screen.getByRole('button', { name: 'Send' }));

  await waitFor(() => expect(screen.getByText('Grounded research response.')).toBeInTheDocument());
  expect(fetchMock).toHaveBeenCalledTimes(2);
});
