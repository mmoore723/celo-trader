/**
 * hooks/useWebSocket.ts — Connects to /ws/live and feeds Zustand bot store.
 * Mounts once at the App level; auto-reconnects on disconnect.
 */
import { useEffect, useRef } from "react";
import { useBotStore } from "../store/bot";

const WS_URL =
  import.meta.env.VITE_WS_URL ??
  `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}/ws/live`;

export function useWebSocket() {
  const wsRef = useRef<WebSocket | null>(null);
  const { setStatus, addLog, setConnected } = useBotStore();

  useEffect(() => {
    let retryTimer: ReturnType<typeof setTimeout>;

    function connect() {
      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.onopen = () => setConnected(true);

      ws.onmessage = (evt) => {
        try {
          const msg = JSON.parse(evt.data);
          if (msg.type === "status") setStatus(msg.data);
          else if (msg.type === "log") addLog(msg.data);
        } catch {
          // ignore malformed
        }
      };

      ws.onclose = () => {
        setConnected(false);
        retryTimer = setTimeout(connect, 3000); // reconnect after 3s
      };

      ws.onerror = () => {
        ws.close();
      };
    }

    connect();

    return () => {
      clearTimeout(retryTimer);
      wsRef.current?.close();
    };
  }, [setStatus, addLog, setConnected]);
}
