from __future__ import annotations

from pathlib import Path


class DotEnvLoader:
    def load(self, path: str | Path) -> dict[str, str]:
        dotenv_path = Path(path)
        if not dotenv_path.is_file():
            return {}
        values: dict[str, str] = {}
        for line in dotenv_path.read_text(encoding="utf-8").splitlines():
            parsed = self._parse_line(line)
            if parsed is not None:
                key, value = parsed
                values[key] = value
        return values

    def _parse_line(self, line: str) -> tuple[str, str] | None:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            return None
        if stripped.startswith("export "):
            stripped = stripped[7:].lstrip()
        key, separator, value = stripped.partition("=")
        if not separator:
            return None
        key = key.strip()
        if not key:
            return None
        return key, self._clean_value(value.strip())

    def _clean_value(self, value: str) -> str:
        if len(value) >= 2 and value[0] == value[-1] == "'":
            return value[1:-1]
        if len(value) >= 2 and value[0] == value[-1] == '"':
            return bytes(value[1:-1], "utf-8").decode("unicode_escape")
        return self._without_comment(value).strip()

    def _without_comment(self, value: str) -> str:
        in_single_quote = False
        in_double_quote = False
        for index, character in enumerate(value):
            if character == "'" and not in_double_quote:
                in_single_quote = not in_single_quote
            elif character == '"' and not in_single_quote:
                in_double_quote = not in_double_quote
            elif character == "#" and not in_single_quote and not in_double_quote:
                if index == 0 or value[index - 1].isspace():
                    return value[:index]
        return value
