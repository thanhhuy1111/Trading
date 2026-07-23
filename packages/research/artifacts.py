"""File-based artifact store for datasets/models/evaluations/evidence.

Layout:

    artifacts/
    ├── datasets/{id}.json          RawCandleDataset metadata
    ├── datasets/{id}.parquet       raw candle table
    ├── training/{id}.json          TrainingDataset metadata
    ├── training/{id}.parquet       joined feature+label table
    ├── models/{id}.json            ModelArtifactRecord metadata
    ├── models/{id}.weights.json    LogisticRegressionWeights / LinearRegressionWeights (plain JSON)
    ├── evaluations/{id}.json       EvaluationReport
    └── evidence/{id}.json          StrategyEvidence (audit copy; source of truth is EvidenceService)

`artifacts/` is already gitignored (repo root .gitignore). Nothing here uses pickle or
joblib: a trained artifact in this pipeline is always the *fitted coefficients* (plain
floats), serialized through the existing `LogisticRegressionWeights`/
`LinearRegressionWeights` Pydantic models from `packages.prediction`, never a pickled
estimator object. There is therefore no untrusted-deserialization trust boundary to
document for Version 1 -- if a future non-linear model (e.g. a tree ensemble) is added,
its inference-time artifact format needs its own explicit decision (e.g. ONNX), not pickle.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Type, TypeVar

import pandas as pd
from pydantic import BaseModel

from packages.research.checksums import checksum_file
from packages.research.exceptions import ArtifactNotFoundError, ChecksumMismatchError

T = TypeVar("T", bound=BaseModel)

DEFAULT_ARTIFACTS_ROOT = "artifacts"
CATEGORIES = ("datasets", "training", "models", "evaluations", "evidence")


class ArtifactStore:
    def __init__(self, root: str = DEFAULT_ARTIFACTS_ROOT) -> None:
        self.root = Path(root)

    def _category_dir(self, category: str) -> Path:
        if category not in CATEGORIES:
            raise ValueError(f"Unknown artifact category '{category}'")
        d = self.root / category
        d.mkdir(parents=True, exist_ok=True)
        return d

    # ---- generic JSON metadata --------------------------------------------------

    def save_metadata(self, category: str, artifact_id: str, record: BaseModel) -> Path:
        path = self._category_dir(category) / f"{artifact_id}.json"
        path.write_text(record.model_dump_json(indent=2), encoding="utf-8")
        return path

    def load_metadata(self, category: str, artifact_id: str, model_cls: Type[T]) -> T:
        path = self._category_dir(category) / f"{artifact_id}.json"
        if not path.exists():
            raise ArtifactNotFoundError(f"{category}/{artifact_id} not found under {self.root}")
        return model_cls.model_validate_json(path.read_text(encoding="utf-8"))

    def list_ids(self, category: str) -> List[str]:
        # Excludes "*.weights.json" (packages/research/runtime_loader.py-style model
        # weight files) so "models" ids are the real ModelArtifactRecord ids, not the
        # {model_id}_direction / {model_id}_return weight artifacts stored alongside them.
        d = self._category_dir(category)
        return sorted(p.stem for p in d.glob("*.json") if not p.name.endswith(".weights.json"))

    # ---- tabular data (parquet) --------------------------------------------------

    def save_dataframe(self, category: str, artifact_id: str, df: pd.DataFrame) -> Path:
        path = self._category_dir(category) / f"{artifact_id}.parquet"
        df.to_parquet(path, index=False)
        return path

    def load_dataframe(self, category: str, artifact_id: str) -> pd.DataFrame:
        path = self._category_dir(category) / f"{artifact_id}.parquet"
        if not path.exists():
            raise ArtifactNotFoundError(f"{category}/{artifact_id}.parquet not found under {self.root}")
        return pd.read_parquet(path)

    def dataframe_checksum(self, category: str, artifact_id: str) -> str:
        path = self._category_dir(category) / f"{artifact_id}.parquet"
        if not path.exists():
            raise ArtifactNotFoundError(f"{category}/{artifact_id}.parquet not found under {self.root}")
        return checksum_file(str(path))

    def verify_dataframe_checksum(self, category: str, artifact_id: str, expected_checksum: str) -> None:
        actual = self.dataframe_checksum(category, artifact_id)
        if actual != expected_checksum:
            raise ChecksumMismatchError(
                f"{category}/{artifact_id}.parquet checksum mismatch: expected {expected_checksum}, got {actual}"
            )

    # ---- plain-JSON model weights (never pickle) --------------------------------

    def save_weights_json(self, artifact_id: str, weights: BaseModel) -> Path:
        path = self._category_dir("models") / f"{artifact_id}.weights.json"
        path.write_text(weights.model_dump_json(indent=2), encoding="utf-8")
        return path

    def load_weights_json(self, artifact_id: str, model_cls: Type[T]) -> T:
        path = self._category_dir("models") / f"{artifact_id}.weights.json"
        if not path.exists():
            raise ArtifactNotFoundError(f"models/{artifact_id}.weights.json not found under {self.root}")
        return model_cls.model_validate_json(path.read_text(encoding="utf-8"))

    # ---- raw JSON (checkpoints etc.) --------------------------------------------

    def save_json(self, category: str, artifact_id: str, suffix: str, data: Dict[str, Any]) -> Path:
        path = self._category_dir(category) / f"{artifact_id}.{suffix}.json"
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        return path

    def load_json(self, category: str, artifact_id: str, suffix: str) -> Optional[Dict[str, Any]]:
        path = self._category_dir(category) / f"{artifact_id}.{suffix}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))


artifact_store = ArtifactStore()
