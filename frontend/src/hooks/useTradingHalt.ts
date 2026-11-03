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
    refetchInterval: 5000,
    refetchIntervalInBackground: true,
    refetchOnWindowFocus: true,
    staleTime: 0,
  });
}
