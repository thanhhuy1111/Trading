import { useState } from 'react';
import { useTranslation, type Lang } from '../i18n';

interface ChatMessage {
  role: 'user' | 'assistant';
  text: string;
}

// Dev-mode RBAC header (apps/api/deps.py: X-Principal-Id / X-Roles, defaults to anonymous
// VIEWER when absent). No real identity provider exists yet in this system -- this is the
// same documented, minimal header contract the backend itself defines, not a bypass of it.
const ADVISOR_HEADERS = { 'Content-Type': 'application/json', 'X-Principal-Id': 'dashboard', 'X-Roles': 'OPERATOR' };

export default function ChatPanel({ lang }: { lang: Lang }) {
  const t = useTranslation(lang);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [configured, setConfigured] = useState(true);

  const send = async () => {
    const message = input.trim();
    if (!message || loading) return;
    setMessages((prev) => [...prev, { role: 'user', text: message }]);
    setInput('');
    setLoading(true);
    setError(null);
    try {
      const res = await fetch('/api/v1/chat', {
        method: 'POST',
        headers: ADVISOR_HEADERS,
        body: JSON.stringify({ conversation_id: conversationId, message }),
      });
      if (res.status === 503) {
        setConfigured(false);
        setMessages((prev) => prev.slice(0, -1));
        return;
      }
      if (!res.ok) {
        setError(t('advisorError'));
        return;
      }
      const data = await res.json();
      setConversationId(data.conversation_id);
      setMessages((prev) => [...prev, { role: 'assistant', text: data.answer }]);
    } catch (e) {
      setError(t('advisorError'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex flex-col h-full">
      <div className="px-4 py-3 border-b border-white/[0.06] flex items-center gap-2">
        <span className="text-lg">🤖</span>
        <div>
          <h2 className="text-sm font-semibold text-slate-200">{t('advisorTitle').replace('🤖 ', '')}</h2>
          <p className="text-[11px] text-slate-500">{t('advisorSubtitle')}</p>
        </div>
      </div>

      {!configured && (
        <div className="mx-4 mt-3 p-3 rounded-lg border border-amber-800/60 bg-amber-950/30 text-amber-300 text-xs">
          {t('advisorNotConfigured')}
        </div>
      )}

      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        {messages.length === 0 && (
          <p className="text-slate-600 text-xs text-center mt-8 leading-relaxed">{t('advisorEmpty')}</p>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div
              className={`max-w-[85%] rounded-xl px-3.5 py-2 text-[13px] leading-relaxed whitespace-pre-wrap ${
                m.role === 'user'
                  ? 'bg-cyan-600 text-white'
                  : 'bg-white/[0.04] text-slate-200 border border-white/[0.06]'
              }`}
            >
              {m.text}
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex justify-start">
            <div className="rounded-xl px-3.5 py-2 text-[13px] bg-white/[0.04] text-slate-500 border border-white/[0.06]">
              {t('advisorSending')}
            </div>
          </div>
        )}
        {error && <p className="text-red-400 text-xs">{error}</p>}
      </div>

      <div className="border-t border-white/[0.06] p-3 space-y-2">
        <div className="flex gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') send(); }}
            placeholder={t('advisorPlaceholder')}
            disabled={loading || !configured}
            className="flex-1 bg-black/30 border border-white/[0.08] rounded-lg px-3 py-2 text-[13px] text-slate-100 placeholder-slate-600 focus:outline-none focus:border-cyan-500/60 disabled:opacity-50"
          />
          <button
            onClick={send}
            disabled={loading || !input.trim() || !configured}
            className="px-4 py-2 bg-cyan-600 hover:bg-cyan-500 disabled:opacity-30 disabled:cursor-not-allowed text-white text-[13px] font-medium rounded-lg transition"
          >
            {t('advisorSend')}
          </button>
        </div>
        <p className="text-[10px] text-slate-600 text-center">{t('advisorDisclaimer')}</p>
      </div>
    </div>
  );
}
