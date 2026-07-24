export type AnalysisState = 'empty' | 'unavailable' | 'available';

export function analysisState(value: Record<string, unknown> | null): AnalysisState {
  if (!value) return 'empty';
  return value.status === 'AVAILABLE' ? 'available' : 'unavailable';
}

export function itemCount(value: unknown): number {
  return Array.isArray(value) ? value.length : 0;
}
