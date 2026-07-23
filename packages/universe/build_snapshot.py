"""Opt-in live universe refresh entrypoint.

    python -m packages.universe.build_snapshot

This is the only place that wires the live network fetch (live_source.py) to the pure
selector (selector.py). Never invoked by the default test suite or imported by anything that
runs automatically — a caller must explicitly run this module to touch the network.
"""

from pathlib import Path

from packages.universe.live_source import fetch_universe_metadata
from packages.universe.models import UniverseSelectionRules
from packages.universe.selector import build_universe_snapshot

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_PATH = REPO_ROOT / "docs" / "research" / "experiments" / "UNIVERSE_SNAPSHOT.json"


def main() -> None:
    metadata = fetch_universe_metadata()
    rules = UniverseSelectionRules()
    snapshot = build_universe_snapshot(metadata, rules)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        f.write(snapshot.model_dump_json(indent=2))

    print(f"[universe] wrote {OUTPUT_PATH}")
    print(f"[universe] eligible: {snapshot.eligible_symbols}")
    print(f"[universe] excluded: {snapshot.exclusion_reasons}")


if __name__ == "__main__":
    main()
