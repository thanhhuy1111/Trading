import { describe, expect, it } from 'vitest';
import { analysisState, itemCount } from './analysisView';

describe('analysis view states', () => {
  it('distinguishes empty, unavailable, and available results', () => {
    expect(analysisState(null)).toBe('empty');
    expect(analysisState({ status: 'UNAVAILABLE' })).toBe('unavailable');
    expect(analysisState({ status: 'AVAILABLE' })).toBe('available');
  });

  it('never fabricates item counts', () => {
    expect(itemCount(undefined)).toBe(0);
    expect(itemCount({})).toBe(0);
    expect(itemCount([{}, {}])).toBe(2);
  });
});
