from __future__ import annotations

from src.type_defs import JsonObject, is_json_object


def as_json_object(value: object) -> JsonObject:
    return value if is_json_object(value) else {}


def string_value(value: object, default: str = "") -> str:
    return default if value is None else str(value)


def optional_string(value: object) -> str | None:
    return str(value) if value is not None else None


def int_value(value: object, default: int) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value)
    return default


def optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value)
    return None


def string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value if item)
