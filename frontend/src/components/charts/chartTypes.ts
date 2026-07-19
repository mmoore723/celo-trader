/**
 * chartTypes.ts — prop-level types shared by the new chart engine.
 * (SimulationOverlay / ReplayTrade stay in lib/chart_types.ts — unchanged.)
 */

export interface PositionLevels {
  entry?: number;
  stop?: number;
  target?: number;
  trail?: number;
  direction?: "long" | "short";
  contracts?: number;
}
