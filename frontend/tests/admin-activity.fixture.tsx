import { createRoot } from "react-dom/client";
import { AdminActivityLog } from "../src/components/AdminActivityLog";
import { useBotStore } from "../src/store/bot";
import "../src/index.css";
useBotStore.getState().setConnected(true);
useBotStore.getState().addLog({ ts: "10:00 AM", level: "INFO", message: "SPY capture received", ticker: "SPY" });
useBotStore.getState().addLog({ ts: "10:01 AM", level: "ERROR", message: "QQQ quote unavailable", ticker: "QQQ" });
createRoot(document.getElementById("root")!).render(<><AdminActivityLog /><button onClick={() => useBotStore.getState().addLog({level:"INFO",message:"New event"})}>Add fixture event</button><button onClick={() => useBotStore.getState().setConnected(false)}>Disconnect fixture</button></>);
