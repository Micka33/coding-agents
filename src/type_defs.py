from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TypeAlias, TypeGuard

JsonScalar: TypeAlias = str | int | float | bool | None
# Mapping/Sequence keep JsonValue covariant so concrete containers such as
# list[JsonObject] or dict[str, str] are assignable without casts.
JsonValue: TypeAlias = JsonScalar | Mapping[str, "JsonValue"] | Sequence["JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]
JsonArray: TypeAlias = list[JsonValue]
JsonMapping: TypeAlias = Mapping[str, JsonValue]


def is_json_value(value: object) -> TypeGuard[JsonValue]:
    if value is None or isinstance(value, (str, int, float, bool)):
        return True
    if isinstance(value, list):
        return all(is_json_value(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and is_json_value(item) for key, item in value.items())
    return False


def is_json_object(value: object) -> TypeGuard[JsonObject]:
    return isinstance(value, dict) and all(
        isinstance(key, str) and is_json_value(item)
        for key, item in value.items()
    )
