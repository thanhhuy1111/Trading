"""Alpha research pipeline CLI.

    python -m packages.research.cli download-data --config configs/research/btc_eth_v1.yaml
    python -m packages.research.cli build-dataset --config configs/research/btc_eth_v1.yaml
    python -m packages.research.cli train-model   --config configs/research/btc_eth_v1.yaml --dataset-id <id>
    python -m packages.research.cli run-walk-forward --config configs/research/btc_eth_v1.yaml \
        --dataset-id <id> --model-id <id>
    python -m packages.research.cli publish-evidence --evaluation-id <id> --strategy-version 1.0.0
    python -m packages.research.cli list-models
    python -m packages.research.cli list-evidence

No subcommand downloads data, trains a model, or publishes evidence merely by importing
this module -- every side effect happens inside a subcommand's handler, invoked only via
`main()` / `if __name__ == "__main__"`. `--dry-run` is honored on every subcommand that
would write to disk or to the runtime registries.

Uses argparse (stdlib) rather than a third-party CLI framework: no CLI framework existed
anywhere else in this repository to be consistent with.
"""

import argparse
import asyncio
import sys
from typing import List, Optional

import pandas as pd

from packages.common.logger import logger
from packages.market_data.adapters.factory import MarketDataProviderFactory
from packages.market_data.models import Timeframe
from packages.recommendation.service import PIPELINE_STRATEGY_NAME, PIPELINE_STRATEGY_VERSION
from packages.research.artifacts import artifact_store
from packages.research.baselines import BASELINE_NAMES, attach_baseline_decisions
from packages.research.candle_repository import CandleRepository, candles_to_dataframe, dataframe_to_candles
from packages.research.config import ResearchConfig, load_research_config
from packages.research.dataset_builder import build_raw_candle_dataset
from packages.research.evaluation import run_walk_forward_evaluation
from packages.research.evidence_publisher import publish_evidence
from packages.research.exceptions import InsufficientDataError, ResearchError
from packages.research.feature_dataset import build_feature_table
from packages.research.labels import build_label_table
from packages.research.models import EvaluationReport, ModelArtifactRecord, RawCandleDataset
from packages.research.overfitting import ExperimentTracker
from packages.research.splits import assign_split_membership, plan_walk_forward_windows
from packages.research.training import (
    build_model_artifact_record,
    prepare_training_matrix,
    train_linear_return_weights,
    train_logistic_direction_weights,
    weights_checksum,
)


def _apply_model_predictions(table: pd.DataFrame, model, feature_names: List[str], threshold: float) -> pd.DataFrame:
    """Adds `model_probability` (probability_up) and `model_decision` (probability_up >=
    threshold) columns to a COPY of `table`. Pure function of the already-trained model's
    coefficients and the table's own feature columns -- no lookahead, since the feature
    columns were themselves built point-in-time (packages.research.feature_dataset).
    """
    out = table.copy()
    if out.empty:
        out["model_probability"] = pd.Series(dtype="float64")
        out["model_decision"] = pd.Series(dtype="bool")
        return out

    def _predict(row) -> float:
        features = {name: float(row[f"feature__{name}"]) for name in feature_names}
        return model.predict_proba(features).probability_up

    out["model_probability"] = out.apply(_predict, axis=1)
    out["model_decision"] = out["model_probability"] >= threshold
    return out


def _cmd_download_data(args: argparse.Namespace) -> int:
    config = load_research_config(args.config)

    if args.dry_run:
        # No CandleRepository/provider is constructed in dry-run mode: the repository's
        # __init__ creates the cache directory as a side effect, which a dry-run must not do.
        for symbol in config.dataset.symbols:
            for tf_str in config.dataset.timeframes:
                print(
                    f"[dry-run] would download {symbol}/{tf_str} "
                    f"{config.dataset.start_time}..{config.dataset.end_time} into {args.output}"
                )
        return 0

    async def _run() -> None:
        provider = MarketDataProviderFactory.create_provider("binance")
        repo = CandleRepository(provider, cache_root=args.output)
        for symbol in config.dataset.symbols:
            for tf_str in config.dataset.timeframes:
                timeframe = Timeframe(tf_str)
                df = await repo.download(symbol, timeframe, config.dataset.start_time, config.dataset.end_time)
                print(f"Downloaded {symbol}/{tf_str}: {len(df)} candles cached under {args.output}")

    asyncio.run(_run())
    return 0


def _load_cached_candles(config: ResearchConfig, cache_root: str) -> List:
    repo = CandleRepository(MarketDataProviderFactory.create_provider("binance"), cache_root=cache_root)
    all_candles = []
    for symbol in config.dataset.symbols:
        for tf_str in config.dataset.timeframes:
            timeframe = Timeframe(tf_str)
            df = repo.load_cached(symbol, timeframe)
            if df is None or df.empty:
                print(f"WARNING: no cached candles for {symbol}/{tf_str} under {cache_root} -- skipping")
                continue
            all_candles.extend(dataframe_to_candles(df))
    return all_candles


def _cmd_build_dataset(args: argparse.Namespace) -> int:
    config = load_research_config(args.config)
    all_candles = _load_cached_candles(config, args.input)

    if not all_candles:
        print("ERROR: no cached candles available -- run download-data first", file=sys.stderr)
        return 1

    if args.dry_run:
        print(f"[dry-run] would build a dataset from {len(all_candles)} cached candles")
        return 0

    try:
        dataset, kept = build_raw_candle_dataset(all_candles, config.dataset, config.config_hash)
    except ResearchError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    artifact_store.save_metadata("datasets", dataset.dataset_id, dataset)
    artifact_store.save_dataframe("datasets", dataset.dataset_id, candles_to_dataframe(kept))
    print(
        f"Built dataset {dataset.dataset_id}: {dataset.candle_count} candles, "
        f"checksum={dataset.dataset_checksum[:16]}..., status={dataset.quality_status.value}, "
        f"duplicates={dataset.duplicate_count}, rejected={dataset.rejected_count}"
    )
    if dataset.quality_issues:
        print(f"Quality issues: {', '.join(dataset.quality_issues)}")
    return 0


def _cmd_train_model(args: argparse.Namespace) -> int:
    config = load_research_config(args.config)
    tracker = ExperimentTracker()
    tracker.record("model", config.model.model_type, config.config_hash)

    dataset = artifact_store.load_metadata("datasets", args.dataset_id, RawCandleDataset)
    kept_df = artifact_store.load_dataframe("datasets", args.dataset_id)
    candles = dataframe_to_candles(kept_df)

    if args.dry_run:
        print(f"[dry-run] would build features+labels from {len(candles)} candles and train {config.model.model_type}")
        return 0

    feature_table = build_feature_table(candles, config.features)
    label_table = build_label_table(candles, config.labels)

    horizon = args.horizon_minutes or config.labels.horizons_minutes[0]
    merged = prepare_training_matrix(feature_table, label_table, config.features.feature_names, horizon)

    windows = plan_walk_forward_windows(
        config.dataset.start_time, config.dataset.end_time, config.splits, config.labels
    )
    window = windows[0]
    classified = assign_split_membership(merged, window)
    train_rows = classified[classified["split"] == "train"]

    try:
        direction_weights = train_logistic_direction_weights(
            train_rows, config.features.feature_names, config.model.model_version,
            config.model.hyperparameters, config.model.random_seed,
        )
        return_weights = train_linear_return_weights(
            train_rows, config.features.feature_names, config.model.model_version
        )
    except InsufficientDataError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    checksum = weights_checksum(direction_weights, return_weights)
    record = build_model_artifact_record(
        model_config=config.model, feature_version=config.features.version, dataset_checksum=dataset.dataset_checksum,
        label_version=config.labels.version, train_window=window.train, validation_window=window.validation,
        test_window=window.test, artifact_path="", artifact_checksum=checksum,
        config_hash=config.config_hash,
    )
    record = record.model_copy(update={"artifact_path": f"models/{record.model_id}"})

    artifact_store.save_metadata("models", record.model_id, record)
    artifact_store.save_weights_json(f"{record.model_id}_direction", direction_weights)
    artifact_store.save_weights_json(f"{record.model_id}_return", return_weights)

    print(f"Trained model {record.model_id} ({record.model_type} {record.model_version}), checksum={checksum[:16]}...")
    print(f"Train rows: {len(train_rows)}, horizon_minutes={horizon}")
    return 0


def _cmd_run_walk_forward(args: argparse.Namespace) -> int:
    config = load_research_config(args.config)
    tracker = ExperimentTracker()

    dataset = artifact_store.load_metadata("datasets", args.dataset_id, RawCandleDataset)
    kept_df = artifact_store.load_dataframe("datasets", args.dataset_id)
    candles = dataframe_to_candles(kept_df)

    if args.dry_run:
        print(f"[dry-run] would run walk-forward evaluation over {len(candles)} candles")
        return 0

    feature_table = build_feature_table(candles, config.features)
    label_table = build_label_table(candles, config.labels)
    label_table = attach_baseline_decisions(label_table, candles)

    horizon = args.horizon_minutes or config.labels.horizons_minutes[0]
    merged = prepare_training_matrix(feature_table, label_table, config.features.feature_names, horizon)

    windows = plan_walk_forward_windows(
        config.dataset.start_time, config.dataset.end_time, config.splits, config.labels
    )
    fold_tables = [assign_split_membership(merged, w) for w in windows]

    subjects = list(BASELINE_NAMES)
    subjects_reports = {}
    for name in subjects:
        tracker.record("baseline", name, config.config_hash)
        report = run_walk_forward_evaluation(
            subject_name=name, subject_type="BASELINE", fold_tables=fold_tables,
            dataset_checksum=dataset.dataset_checksum, config_hash=config.config_hash,
            decision_column=f"baseline__{name}", experiments_tried=tracker.total_trials,
        )
        artifact_store.save_metadata("evaluations", report.evaluation_id, report)
        subjects_reports[name] = report
        print(
            f"[{name}] evaluation_id={report.evaluation_id} trades={report.aggregate_metrics.trade_count} "
            f"net_pnl_bps={report.aggregate_metrics.net_pnl_bps}"
        )

    if args.model_id:
        from packages.prediction.direction_model import LogisticRegressionDirectionModel, LogisticRegressionWeights
        from packages.recommendation.config import recommendation_config

        model_record = artifact_store.load_metadata("models", args.model_id, ModelArtifactRecord)
        direction_weights = artifact_store.load_weights_json(f"{args.model_id}_direction", LogisticRegressionWeights)
        model = LogisticRegressionDirectionModel(direction_weights)
        threshold = float(recommendation_config.min_probability_profit)
        fold_tables = [
            _apply_model_predictions(table, model, config.features.feature_names, threshold) for table in fold_tables
        ]

        tracker.record("model", model_record.model_version, config.config_hash)
        model_report = run_walk_forward_evaluation(
            subject_name=model_record.model_version, subject_type="MODEL", fold_tables=fold_tables,
            dataset_checksum=dataset.dataset_checksum, config_hash=config.config_hash,
            decision_column="model_decision", probability_column="model_probability",
            experiments_tried=tracker.total_trials,
        )
        artifact_store.save_metadata("evaluations", model_report.evaluation_id, model_report)
        subjects_reports[model_record.model_version] = model_report
        calibration_score = model_report.calibration.calibration_score if model_report.calibration else None
        print(
            f"[{model_record.model_version}] evaluation_id={model_report.evaluation_id} "
            f"trades={model_report.aggregate_metrics.trade_count} "
            f"net_pnl_bps={model_report.aggregate_metrics.net_pnl_bps} "
            f"calibration_score={calibration_score}"
        )

    return 0


def _cmd_publish_evidence(args: argparse.Namespace) -> int:
    config = load_research_config(args.config)
    evaluation = artifact_store.load_metadata("evaluations", args.evaluation_id, EvaluationReport)

    if args.dry_run:
        print(f"[dry-run] would publish evidence for {evaluation.subject_name} from evaluation {args.evaluation_id}")
        return 0

    evidence = publish_evidence(
        evaluation, strategy_name=args.strategy_name or PIPELINE_STRATEGY_NAME,
        strategy_version=args.strategy_version or PIPELINE_STRATEGY_VERSION,
        model_version=evaluation.subject_name, feature_version=config.features.version,
        research_approval_config=config.approval,
    )
    print(f"Published evidence {evidence.evidence_id}: status={evidence.status.value} reasons={evidence.reason_codes}")
    return 0


def _cmd_list_models(_args: argparse.Namespace) -> int:
    for model_id in artifact_store.list_ids("models"):
        print(model_id)
    return 0


def _cmd_list_evidence(_args: argparse.Namespace) -> int:
    for evidence_id in artifact_store.list_ids("evidence"):
        print(evidence_id)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m packages.research.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("download-data", help="Download and cache historical candles")
    p.add_argument("--config", required=True)
    p.add_argument("--output", default="data/research/candles")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=_cmd_download_data)

    p = sub.add_parser("build-dataset", help="Validate cached candles into a checksummed dataset artifact")
    p.add_argument("--config", required=True)
    p.add_argument("--input", default="data/research/candles")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=_cmd_build_dataset)

    p = sub.add_parser("train-model", help="Build features+labels and train the configured model")
    p.add_argument("--config", required=True)
    p.add_argument("--dataset-id", required=True)
    p.add_argument("--horizon-minutes", type=int, default=None)
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=_cmd_train_model)

    p = sub.add_parser("run-walk-forward", help="Evaluate baselines (and optionally a trained model) walk-forward")
    p.add_argument("--config", required=True)
    p.add_argument("--dataset-id", required=True)
    p.add_argument("--model-id", default=None)
    p.add_argument("--horizon-minutes", type=int, default=None)
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=_cmd_run_walk_forward)

    p = sub.add_parser("publish-evidence", help="Publish an evaluation report as StrategyEvidence")
    p.add_argument("--config", required=True)
    p.add_argument("--evaluation-id", required=True)
    p.add_argument("--strategy-name", default=None)
    p.add_argument("--strategy-version", default=None)
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=_cmd_publish_evidence)

    p = sub.add_parser("list-models", help="List trained model artifact IDs")
    p.set_defaults(func=_cmd_list_models)

    p = sub.add_parser("list-evidence", help="List published evidence IDs")
    p.set_defaults(func=_cmd_list_evidence)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ResearchError as exc:
        logger.error("research_cli_error", extra={"command": args.command, "error": str(exc)})
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
