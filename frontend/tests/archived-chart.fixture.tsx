// Offline chart-range UI fixture. All API calls are mocked by the browser test.
import {createRoot} from 'react-dom/client';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {MemoryRouter} from 'react-router-dom';
import {AuthProvider} from '../src/contexts/AuthContext';
import {LiveTrading} from '../src/pages/LiveTrading';
import '../src/index.css';
createRoot(document.getElementById('root')!).render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><AuthProvider><MemoryRouter><LiveTrading/></MemoryRouter></AuthProvider></QueryClientProvider>);
