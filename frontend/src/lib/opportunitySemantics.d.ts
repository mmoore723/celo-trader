import type { ScannerOpportunity } from "./api";

export type OpportunityLifecycle = "watching" | "pricing" | "ready" | "stopped" | "entered" | "research" | string;
export function opportunityLifecycle(entry: Partial<ScannerOpportunity>): OpportunityLifecycle;
export function isOperationalOpportunity(entry: Partial<ScannerOpportunity>): boolean;
export function lifecycleCopy(entry: Partial<ScannerOpportunity>): { title: string; badge: string; detail: string };
export function dedupeLatestEpisodes(entries: ScannerOpportunity[], limit?: number): ScannerOpportunity[];
export function collapseOpportunityEpisodes(entries: ScannerOpportunity[]): ScannerOpportunity[];
