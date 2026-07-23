# Alerting Policy & Threshold Rules

## Alert Severities
- `INFO`: Informational event requiring no immediate operator action.
- `WARNING`: Early degradation signal (e.g. stream disconnect).
- `ERROR`: Functional failure in non-critical pipeline component.
- `CRITICAL`: Risk Governor Hard Stop or system-wide data corruption.

## Anti-Noise Controls
- Alert threshold `for_duration_seconds` prevents false positives from transient spikes.
- Alert fingerprinting deduplicates repetitive occurrences.
- Cooldown timers suppress repeated alerts until resolution.
