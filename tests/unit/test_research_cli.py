"""Offline unit tests for packages/research/cli.py -- parser wiring and --dry-run paths.

Full end-to-end CLI runs against real Binance data are exercised manually (see
docs/ALPHA_RESEARCH_RUNBOOK.md and docs/ALPHA_RESEARCH_IMPLEMENTATION_REPORT.md for the
exact commands and results of that run) -- not in the default offline test suite.
"""

from pathlib import Path

from packages.research.cli import build_parser, main


def test_build_parser_registers_all_required_subcommands():
    parser = build_parser()
    subcommand_names = set()
    for action in parser._subparsers._group_actions:  # noqa: SLF001 - argparse introspection for a coverage test
        subcommand_names.update(action.choices.keys())

    assert subcommand_names == {
        "download-data", "build-dataset", "train-model", "run-walk-forward",
        "publish-evidence", "list-models", "list-evidence",
    }


def test_download_data_dry_run_does_not_touch_network_or_disk(tmp_path, capsys):
    config_path = tmp_path / "cfg.yaml"
    config_path.write_text(
        """
name: test
dataset:
  symbols: ["BTCUSDT"]
  timeframes: ["1h"]
  start_time: "2026-01-01T00:00:00+00:00"
  end_time: "2026-01-02T00:00:00+00:00"
"""
    )
    output_dir = tmp_path / "candles"

    exit_code = main(["download-data", "--config", str(config_path), "--output", str(output_dir), "--dry-run"])

    assert exit_code == 0
    assert not output_dir.exists()  # dry-run must not create the cache directory
    captured = capsys.readouterr()
    assert "dry-run" in captured.out
    assert "BTCUSDT/1h" in captured.out


def test_build_dataset_dry_run_reports_no_cached_candles(tmp_path, capsys):
    config_path = tmp_path / "cfg.yaml"
    config_path.write_text(
        """
name: test
dataset:
  symbols: ["BTCUSDT"]
  timeframes: ["1h"]
  start_time: "2026-01-01T00:00:00+00:00"
  end_time: "2026-01-02T00:00:00+00:00"
"""
    )
    empty_input = tmp_path / "empty_candles"
    empty_input.mkdir()

    exit_code = main(["build-dataset", "--config", str(config_path), "--input", str(empty_input), "--dry-run"])

    assert exit_code == 1  # no cached candles -> real error, dry-run still checks preconditions
    captured = capsys.readouterr()
    assert "no cached candles" in captured.err.lower()


def test_list_models_and_list_evidence_run_without_error(tmp_path, monkeypatch):
    import packages.research.artifacts as artifacts_module
    import packages.research.cli as cli_module

    isolated_store = artifacts_module.ArtifactStore(root=str(tmp_path / "artifacts"))
    monkeypatch.setattr(cli_module, "artifact_store", isolated_store)

    assert main(["list-models"]) == 0
    assert main(["list-evidence"]) == 0


def test_example_research_config_loads_and_cli_recognizes_it():
    repo_root = Path(__file__).resolve().parents[2]
    config_path = repo_root / "configs" / "research" / "btc_eth_v1.yaml"
    assert config_path.exists()

    exit_code = main(["download-data", "--config", str(config_path), "--output", "/tmp/does-not-matter", "--dry-run"])
    assert exit_code == 0
