from __future__ import annotations

from typing import Any

from .team_loader_error import TeamLoaderError


class YamlParser:
    """Small YAML subset parser for team loader configuration files."""

    def parse(self, text: str) -> Any:
        self._lines = text.splitlines()
        value, index = self._parse_block(0, 0)
        index = self._skip_blank(index)
        if index < len(self._lines):
            raise TeamLoaderError(f"Unexpected YAML content on line {index + 1}.")
        return value

    def _parse_block(self, index: int, indent: int) -> tuple[Any, int]:
        index = self._skip_blank(index)
        if index >= len(self._lines):
            return {}, index
        if self._indent_of(index) < indent:
            return {}, index
        if self._stripped(index).startswith("- "):
            return self._parse_list(index, indent)
        return self._parse_mapping(index, indent)

    def _parse_mapping(self, index: int, indent: int) -> tuple[dict[str, Any], int]:
        result: dict[str, Any] = {}
        while index < len(self._lines):
            index = self._skip_blank(index)
            if index >= len(self._lines) or self._indent_of(index) < indent:
                break
            if self._indent_of(index) > indent:
                raise TeamLoaderError(f"Unexpected indentation on line {index + 1}.")
            stripped = self._stripped(index)
            if stripped.startswith("- "):
                break
            key, value = self._split_key_value(stripped, index)
            if value == ">":
                result[key], index = self._parse_folded_scalar(index + 1, indent)
            elif value == "|":
                result[key], index = self._parse_literal_scalar(index + 1, indent)
            elif value == "":
                next_index = self._skip_blank(index + 1)
                if next_index >= len(self._lines) or self._indent_of(next_index) <= indent:
                    result[key] = None
                    index += 1
                else:
                    result[key], index = self._parse_block(next_index, self._indent_of(next_index))
            else:
                result[key] = self._parse_scalar(value)
                index += 1
        return result, index

    def _parse_list(self, index: int, indent: int) -> tuple[list[Any], int]:
        result: list[Any] = []
        while index < len(self._lines):
            index = self._skip_blank(index)
            if index >= len(self._lines) or self._indent_of(index) < indent:
                break
            if self._indent_of(index) != indent or not self._stripped(index).startswith("- "):
                break
            item_text = self._stripped(index)[2:].strip()
            if item_text == "":
                next_index = self._skip_blank(index + 1)
                if next_index >= len(self._lines) or self._indent_of(next_index) <= indent:
                    result.append(None)
                    index += 1
                else:
                    item, index = self._parse_block(next_index, self._indent_of(next_index))
                    result.append(item)
            elif self._looks_like_mapping_item(item_text):
                key, value = self._split_key_value(item_text, index)
                item_dict: dict[str, Any] = {key: self._parse_scalar(value) if value else None}
                next_index = self._skip_blank(index + 1)
                if next_index < len(self._lines) and self._indent_of(next_index) > indent:
                    nested, index = self._parse_mapping(next_index, self._indent_of(next_index))
                    item_dict.update(nested)
                else:
                    index += 1
                result.append(item_dict)
            else:
                result.append(self._parse_scalar(item_text))
                index += 1
        return result, index

    def _parse_folded_scalar(self, index: int, parent_indent: int) -> tuple[str, int]:
        values: list[str] = []
        while index < len(self._lines):
            if self._is_blank(index):
                values.append("")
                index += 1
                continue
            if self._indent_of(index) <= parent_indent:
                break
            values.append(self._stripped(index))
            index += 1
        return self._fold_lines(values), index

    def _parse_literal_scalar(self, index: int, parent_indent: int) -> tuple[str, int]:
        values: list[str] = []
        while index < len(self._lines):
            if self._is_blank(index):
                values.append("")
                index += 1
                continue
            if self._indent_of(index) <= parent_indent:
                break
            values.append(self._line_without_common_indent(index, parent_indent + 2))
            index += 1
        return "\n".join(values), index

    def _fold_lines(self, lines: list[str]) -> str:
        paragraphs: list[str] = []
        current: list[str] = []
        for line in lines:
            if line == "":
                if current:
                    paragraphs.append(" ".join(current))
                    current = []
                paragraphs.append("")
            else:
                current.append(line)
        if current:
            paragraphs.append(" ".join(current))
        return "\n".join(paragraphs).strip()

    def _parse_scalar(self, value: str) -> Any:
        value = value.strip()
        if value in {"null", "Null", "NULL", "~"}:
            return None
        if value in {"true", "True", "TRUE"}:
            return True
        if value in {"false", "False", "FALSE"}:
            return False
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            return value[1:-1]
        if value.isdigit() or (value.startswith("-") and value[1:].isdigit()):
            return int(value)
        return value

    def _split_key_value(self, text: str, index: int) -> tuple[str, str]:
        if ":" not in text:
            raise TeamLoaderError(f"Expected YAML key/value on line {index + 1}.")
        key, value = text.split(":", 1)
        key = key.strip()
        if not key:
            raise TeamLoaderError(f"Empty YAML key on line {index + 1}.")
        return key, value.strip()

    def _looks_like_mapping_item(self, text: str) -> bool:
        return ":" in text and not text.startswith(("http://", "https://"))

    def _skip_blank(self, index: int) -> int:
        while index < len(self._lines) and self._is_blank_or_comment(index):
            index += 1
        return index

    def _is_blank_or_comment(self, index: int) -> bool:
        stripped = self._lines[index].strip()
        return stripped == "" or stripped.startswith("#")

    def _is_blank(self, index: int) -> bool:
        return self._lines[index].strip() == ""

    def _indent_of(self, index: int) -> int:
        line = self._lines[index]
        return len(line) - len(line.lstrip(" "))

    def _stripped(self, index: int) -> str:
        return self._lines[index].strip()

    def _line_without_common_indent(self, index: int, indent: int) -> str:
        line = self._lines[index]
        return line[indent:] if len(line) >= indent else ""
