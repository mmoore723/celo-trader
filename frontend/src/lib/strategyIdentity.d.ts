export function strategyName(name: string): string;
export function exitReason(reason?: string | null): string;
export function strategyVariant(id: string): string;
export function strategyVersion(version?: string): string;
export function normalizeStrategyLabels<T>(value: T): T;
export function groupStrategies<T extends { strategy_id: string; display_name: string }>(strategies: T[]): { name: string; strategies: T[] }[];
