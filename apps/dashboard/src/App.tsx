import { useEffect, useState } from 'react';
import CandleChart from './components/CandleChart';
import ChatPanel from './components/ChatPanel';
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

  useEffect(() => {
    const checkBackend = async () => {
      try {
        const res = await fetch('/api/market-data/live-prices?symbols=BTCUSDT');
        setIsBackendAvailable(res.ok);
      } catch {
        setIsBackendAvailable(false);
      }
    };
    checkBackend();
    const interval = setInterval(checkBackend, 10000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="h-screen flex flex-col bg-slate-950 text-slate-100 overflow-hidden">
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

      <main className="flex-1 flex flex-col md:flex-row min-h-0">
        <div className="flex-1 min-w-0 min-h-0">
          <CandleChart lang={lang} />
        </div>
        <div className="w-full md:w-[380px] shrink-0 border-t md:border-t-0 md:border-l border-white/[0.06] h-64 md:h-auto">
          <ChatPanel lang={lang} />
        </div>
      </main>
    </div>
  );
}
