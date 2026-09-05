export interface StrategyPerformanceRow {
  strategy_id: string;
  trades: number;
  wins: number;
  losses: number;
  profit_factor: number;
  total_pnl: number;
  current_version?: string | null;
  current_version_trades?: number;
  current_version_wins?: number;
  current_version_losses?: number;
  current_version_total_pnl?: number;
  current_version_profit_factor?: number;
  prior_or_unversioned_trades?: number;
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

export function currentVersionPerformance(
  row: StrategyPerformanceRow | null,
): StrategyPerformanceRow | null;

export function strategyPerformanceState(
  row: StrategyPerformanceRow | null,
  target?: number,
  minimumTrades?: number,
): StrategyPerformanceState;
