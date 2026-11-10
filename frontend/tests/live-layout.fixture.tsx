import {createRoot} from 'react-dom/client';
import {MemoryRouter} from 'react-router-dom';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {LiveTrading} from '../src/pages/LiveTrading';
import {Topbar} from '../src/components/layout/Topbar';
import {useBotStore, type BotStatus} from '../src/store/bot';
import '../src/index.css';
useBotStore.setState({connected:true,status:{mode:'paper',running:true,broker_connected:true,account_balance:19859.9,day_start_balance:20000,session_pnl:-140.1,options_buying_power:16219.9,open_positions:{}} as BotStatus});
createRoot(document.getElementById('root')!).render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><MemoryRouter><Topbar /><LiveTrading /></MemoryRouter></QueryClientProvider>);
