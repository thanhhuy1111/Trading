"""Registry for derivatives feature calculators (Multi-Agent Trading Advisor plan, Phase 2).

A separate registry from `packages.features.registry.feature_registry`, mirroring its shape
exactly. `FeatureCalculator.calculate()` is structurally pinned to `List[Candle]`/
`FeatureContext`; a derivatives calculator's `List[DerivativesSnapshot]`/
`DerivativesFeatureContext` signature is not structurally compatible under mypy's (correct)
contravariant Protocol checking, even though nothing about candle-shaped and derivatives-shaped
calculators actually needs to share one dict at runtime.
"""

from typing import Dict, List, Optional, Protocol, Tuple

from packages.features.derivatives_models import DerivativesFeatureContext
from packages.features.models import FeatureDefinition, FeatureValue
from packages.market_data.derivatives_models import DerivativesSnapshot


class DerivativesFeatureCalculator(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def version(self) -> str: ...

    @property
    def category(self) -> str: ...

    @property
    def required_lookback(self) -> int: ...

    def calculate(
        self,
        snapshots: List[DerivativesSnapshot],
        context: DerivativesFeatureContext,
    ) -> FeatureValue: ...


class DerivativesFeatureRegistry:
    """Central registry for derivatives feature calculators, definitions, and set compositions."""

    def __init__(self) -> None:
        self._calculators: Dict[Tuple[str, str], DerivativesFeatureCalculator] = {}
        self._definitions: Dict[Tuple[str, str], FeatureDefinition] = {}

    def register(self, definition: FeatureDefinition, calculator: DerivativesFeatureCalculator) -> None:
        key = (definition.name, definition.version)
        if key in self._definitions:
            raise ValueError(f"Derivatives feature '{definition.name}' v{definition.version} is already registered")
        self._definitions[key] = definition
        self._calculators[key] = calculator

    def get_calculator(self, name: str, version: str = "1.0.0") -> Optional[DerivativesFeatureCalculator]:
        return self._calculators.get((name, version))

    def get_definition(self, name: str, version: str = "1.0.0") -> Optional[FeatureDefinition]:
        return self._definitions.get((name, version))

    def list_definitions(self) -> List[FeatureDefinition]:
        return list(self._definitions.values())

    def list_calculators(self) -> List[DerivativesFeatureCalculator]:
        return list(self._calculators.values())


# Singleton instance
derivatives_feature_registry = DerivativesFeatureRegistry()
