"""Small immutable containers used by validated, checksum-sensitive contracts."""

from collections.abc import Iterator, Mapping
from typing import Any, Generic, TypeVar, get_args

from pydantic import GetCoreSchemaHandler
from pydantic_core import CoreSchema, core_schema

Key = TypeVar("Key")
Value = TypeVar("Value")


class FrozenMapping(Mapping[Key, Value], Generic[Key, Value]):
    """An immutable, Pydantic-serializable mapping that does not inherit from ``dict``."""

    __slots__ = ("_items",)
    _items: tuple[tuple[Key, Value], ...]

    def __init__(self, value: Mapping[Key, Value]) -> None:
        object.__setattr__(self, "_items", tuple(value.items()))

    def __setattr__(self, name: str, value: object) -> None:
        raise TypeError("FrozenMapping is immutable")

    def __getitem__(self, key: Key) -> Value:
        for item_key, item_value in self._items:
            if item_key == key:
                return item_value
        raise KeyError(key)

    def __iter__(self) -> Iterator[Key]:
        return (key for key, _ in self._items)

    def __len__(self) -> int:
        return len(self._items)

    @classmethod
    def __get_pydantic_core_schema__(
        cls,
        source_type: Any,
        handler: GetCoreSchemaHandler,
    ) -> CoreSchema:
        key_type, value_type = get_args(source_type) or (Any, Any)
        dict_schema = core_schema.dict_schema(
            keys_schema=handler.generate_schema(key_type),
            values_schema=handler.generate_schema(value_type),
        )
        return core_schema.no_info_after_validator_function(
            cls,
            dict_schema,
            serialization=core_schema.plain_serializer_function_ser_schema(
                lambda value: dict(value),
                return_schema=dict_schema,
            ),
        )
