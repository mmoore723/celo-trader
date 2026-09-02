export interface StrategyPerformanceRow {
  strategy_id: string;
  trades: number;
  wins: number;
  losses: number;
  profit_factor: number;
  total_pnl: number;
}

export interface StrategyPerformanceState {
  trades: number;
  hasResult: boolean;
  enoughEvidence: boolean;
  meetsTarget: boolean;
  pfLabel: string;
}

export function strategyPerformanceForId(
  rows: StrategyPerformanceRow[] | undefined,
  strategyId: string,
): StrategyPerformanceRow | null;

export function strategyPerformanceState(
  row: StrategyPerformanceRow | null,
  target?: number,
  minimumTrades?: number,
): StrategyPerformanceState;
