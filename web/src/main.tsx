import '@fontsource-variable/inter';
import './styles/global.css';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from '@/app/App';
import { loadPrefs, resolveTheme } from '@/app/preferences';
import { useApp } from '@/app/store';
import { applyUrl, parseHash } from '@/app/url';
import { madridDayType } from '@/lib/format';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 2,
      retryDelay: (n) => Math.min(4000, 800 * 2 ** n),
    },
  },
});

// initial state: persisted prefs < today's day type < URL
const prefs = loadPrefs();
const initial = parseHash(window.location.hash);
useApp.setState({
  ...(prefs.lang ? { lang: prefs.lang } : {}),
  ...(prefs.themePref ? { themePref: prefs.themePref } : {}),
  day: madridDayType(),
});
applyUrl(initial);
const theme = resolveTheme(useApp.getState().themePref);
useApp.setState({ theme });
document.documentElement.dataset.theme = theme;

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App initial={initial} />
    </QueryClientProvider>
  </StrictMode>,
);
