"""Converts real campaign gate results into EvidenceRecords.

Reads only already-computed campaign artifacts (GATE_RESULTS.csv, EXPERIMENT_LEDGER.csv,
CAMPAIGN_MANIFEST.json) — no re-running, no re-scoring, no invented numbers.
"""

import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List

from packages.evidence.models import (
    EvidenceKey,
    EvidenceRecord,
    EvidenceStatus,
    compute_evidence_dataset_checksum,
)
from packages.research.gate import GATE_VERSION

MODEL_TYPE_RULE_BASED = "RULE_BASED_MULTI_AGENT"
MODEL_VERSION_NONE = "n/a"  # Checkpoint 1 has no trained ML model yet (see plan Phase 7)
FEATURE_VERSION = "standard_v1"
LABEL_VERSION = "meta_label_v1"  # net_return_bps > 0 => ACCEPT, else REJECT (Phase 8 target)

# Evidence freshness window: an APPROVED record older than this is treated as STALE at lookup
# time rather than trusted indefinitely. Conservative default for a research-stage system with
# no live/paper trading yet — revisit once Phase 19 (continuous monitoring) is built.
DEFAULT_EVIDENCE_TTL = timedelta(days=30)


def _read_csv(path: Path) -> List[Dict]:
    with open(path) as f:
        return list(csv.DictReader(f))


def build_evidence_records(
    experiments_dir: Path,
    timeframe: str,
    strategy_version: str = "1.0.0",
    ttl: timedelta = DEFAULT_EVIDENCE_TTL,
) -> List[EvidenceRecord]:
    gate_rows = _read_csv(experiments_dir / "GATE_RESULTS.csv")
    ledger_rows = _read_csv(experiments_dir / "EXPERIMENT_LEDGER.csv")
    manifest = json.loads((experiments_dir / "CAMPAIGN_MANIFEST.json").read_text())

    code_commit = manifest["git_sha"]
    promoted_configs = set(manifest.get("configs_promoted_all_symbols", []))
    generated_at = datetime.now(timezone.utc)

    # dataset_checksum per (symbol, config) = combined checksum of its 3 fold datasets.
    fold_checksums: Dict[tuple, List[str]] = {}
    for row in ledger_rows:
        if row["run_type"] != "OOS_FOLD" or row["status"] != "OK":
            continue
        key = (row["symbol"], row["config_name"])
        fold_checksums.setdefault(key, []).append(row["dataset_checksum"])

    records: List[EvidenceRecord] = []
    for row in gate_rows:
        symbol = row["symbol"]
        config_name = row["config_name"]
        config_hash = row["config_hash"]
        passed = row["passed"] == "True"
        reasons = [r for r in row["reasons"].split(";") if r]
        total_oos_trades = int(row["total_oos_trades"])

        checksums = fold_checksums.get((symbol, config_name), [])
        dataset_checksum = compute_evidence_dataset_checksum(checksums) if checksums else "NO_DATA"

        if passed and config_name in promoted_configs:
            status = EvidenceStatus.UNIVERSAL_APPROVED
        elif passed:
            status = EvidenceStatus.ASSET_SPECIFIC_APPROVED
        elif total_oos_trades < 20:
            status = EvidenceStatus.INSUFFICIENT
        elif row["aggregate_net_profit"] and float(row["aggregate_net_profit"]) > 0 and not any(
            r.startswith("AGGREGATE_NET_PNL_NOT_POSITIVE") or r.startswith("TOTAL_OOS_TRADES")
            for r in reasons
        ):
            # Net-positive in aggregate but failed on a softer criterion (Sharpe/drawdown/fold
            # ratio) — worth further research, but explicitly NOT tradeable evidence.
            status = EvidenceStatus.RESEARCH_ONLY
        else:
            status = EvidenceStatus.REJECTED

        key = EvidenceKey(
            strategy_name=config_name,
            strategy_version=strategy_version,
            symbol=symbol,
            timeframe=timeframe,
            model_type=MODEL_TYPE_RULE_BASED,
            model_version=MODEL_VERSION_NONE,
            feature_version=FEATURE_VERSION,
            label_version=LABEL_VERSION,
            dataset_checksum=dataset_checksum,
            gate_version=GATE_VERSION,
            config_hash=config_hash,
            code_commit=code_commit,
        )

        expires_at = (
            generated_at + ttl
            if status in (EvidenceStatus.UNIVERSAL_APPROVED, EvidenceStatus.ASSET_SPECIFIC_APPROVED)
            else None
        )

        records.append(EvidenceRecord(
            key=key,
            status=status,
            generated_at=generated_at,
            total_oos_trades=total_oos_trades,
            mean_oos_sharpe=row["mean_oos_sharpe"] or None,
            worst_fold_drawdown_pct=row["worst_fold_drawdown_pct"] or None,
            aggregate_net_profit=row["aggregate_net_profit"] or None,
            reasons=reasons,
            expires_at=expires_at,
        ))

    return records


def write_evidence_csv(records: List[EvidenceRecord], path: Path) -> None:
    fieldnames = [
        "strategy_name", "strategy_version", "symbol", "timeframe", "model_type", "model_version",
        "feature_version", "label_version", "dataset_checksum", "gate_version", "config_hash",
        "code_commit", "status", "total_oos_trades", "mean_oos_sharpe", "worst_fold_drawdown_pct",
        "aggregate_net_profit", "reasons", "generated_at", "expires_at",
    ]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in records:
            writer.writerow({
                **r.key._asdict(),
                "status": r.status.value,
                "total_oos_trades": r.total_oos_trades,
                "mean_oos_sharpe": r.mean_oos_sharpe or "",
                "worst_fold_drawdown_pct": r.worst_fold_drawdown_pct or "",
                "aggregate_net_profit": r.aggregate_net_profit or "",
                "reasons": ";".join(r.reasons),
                "generated_at": r.generated_at.isoformat(),
                "expires_at": r.expires_at.isoformat() if r.expires_at else "",
            })
    print(f"[evidence] wrote {path} ({len(records)} records)")


if __name__ == "__main__":
    repo_root = Path(__file__).resolve().parents[2]
    experiments_dir = repo_root / "docs" / "research" / "experiments"
    records = build_evidence_records(experiments_dir, timeframe="1d")
    write_evidence_csv(records, experiments_dir / "EVIDENCE_RECORDS.csv")

    from collections import Counter
    print(Counter(r.status.value for r in records))
