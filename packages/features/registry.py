from typing import Dict, List, Optional, Protocol, Tuple

from packages.features.models import FeatureContext, FeatureDefinition, FeatureValue
from packages.market_data.models import Candle


class FeatureCalculator(Protocol):
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
        candles: List[Candle],
        context: FeatureContext,
    ) -> FeatureValue: ...


class FeatureRegistry:
    """Central Feature Registry for feature calculators, definitions, and set compositions."""

    def __init__(self) -> None:
        self._calculators: Dict[Tuple[str, str], FeatureCalculator] = {}
        self._definitions: Dict[Tuple[str, str], FeatureDefinition] = {}

    def register(self, definition: FeatureDefinition, calculator: FeatureCalculator) -> None:
        key = (definition.name, definition.version)
        if key in self._definitions:
            raise ValueError(f"Feature '{definition.name}' v{definition.version} is already registered")
        self._definitions[key] = definition
        self._calculators[key] = calculator

    def get_calculator(self, name: str, version: str = "1.0.0") -> Optional[FeatureCalculator]:
        return self._calculators.get((name, version))

    def get_definition(self, name: str, version: str = "1.0.0") -> Optional[FeatureDefinition]:
        return self._definitions.get((name, version))

    def list_definitions(self) -> List[FeatureDefinition]:
        return list(self._definitions.values())

    def list_calculators(self) -> List[FeatureCalculator]:
        return list(self._calculators.values())


# Singleton instance
feature_registry = FeatureRegistry()
