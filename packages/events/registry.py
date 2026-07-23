from typing import Any, Dict, Optional, Protocol, Tuple, Type

from pydantic import BaseModel


class EventUpcaster(Protocol):
    """Protocol for event schema upcasting across version transitions."""
    def can_upcast(self, event_type: str, from_version: int) -> bool:
        ...

    def upcast(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
        ...


class EventRegistry:
    """Registry mapping (event_type, schema_version) pairs to Pydantic models."""

    _models: Dict[Tuple[str, int], Type[BaseModel]] = {}
    _upcasters: Dict[Tuple[str, int], EventUpcaster] = {}

    @classmethod
    def register(cls, event_type: str, version: int = 1):
        """Decorator to register a Pydantic model for an event type and version."""
        def decorator(model_cls: Type[BaseModel]):
            cls._models[(event_type, version)] = model_cls
            return model_cls
        return decorator

    @classmethod
    def register_upcaster(cls, event_type: str, from_version: int, upcaster: EventUpcaster):
        """Register an upcaster for schema upgrades."""
        cls._upcasters[(event_type, from_version)] = upcaster

    @classmethod
    def get_model(cls, event_type: str, version: int = 1) -> Optional[Type[BaseModel]]:
        return cls._models.get((event_type, version))

    @classmethod
    def deserialize_payload(cls, event_type: str, version: int, payload: Dict[str, Any]) -> BaseModel:
        """Deserializes payload into registered model or raises ValueError."""
        # Upcast if matching upcaster exists
        upcaster = cls._upcasters.get((event_type, version))
        if upcaster and upcaster.can_upcast(event_type, version):
            payload = upcaster.upcast(payload)
            version += 1

        model_cls = cls.get_model(event_type, version)
        if not model_cls:
            raise ValueError(f"Unsupported event schema: type='{event_type}', version={version}")

        return model_cls.model_validate(payload)
