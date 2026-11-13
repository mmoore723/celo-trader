import { useQuery } from "@tanstack/react-query";

type Halt = { halted: boolean; reason: string | null; close_pending: boolean; scope: string; session: string; realized_loss_limit_usd?: number; equity_loss_limit_usd?: number };
const base = import.meta.env.VITE_API_URL ?? "";

export function useTradingHalt() {
  return useQuery<Halt>({
    queryKey: ["trading-halt"],
    queryFn: async () => {
      const response = await fetch(`${base}/api/bot/halt`, { credentials: "include" });
      if (!response.ok) throw new Error("Unable to verify trading halt status.");
      return response.json();
    },
    refetchInterval: query => {
      if (query.state.data?.halted || query.state.data?.close_pending) return 5000;
      const parts = Object.fromEntries(new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", weekday: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).formatToParts(new Date()).map(p => [p.type, p.value]));
      const minute = Number(parts.hour) * 60 + Number(parts.minute);
      const regularClock = !["Sat", "Sun"].includes(parts.weekday) && minute >= 570 && minute < 960;
      return regularClock ? 5000 : 60000;
    },
    retry: 1,
    retryDelay: 1000,
    refetchIntervalInBackground: true,
    refetchOnWindowFocus: true,
    staleTime: 5000,
  });
}
