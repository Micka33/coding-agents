from __future__ import annotations

from pathlib import Path

from .mdc_document import MdcDocument
from .team_loader_error import TeamLoaderError
from .yaml_parser import YamlParser


class MdcParser:
    def __init__(self, yaml_parser: YamlParser | None = None) -> None:
        self._yaml_parser = yaml_parser or YamlParser()

    def parse_file(self, path: Path | str) -> MdcDocument:
        resolved = Path(path)
        text = resolved.read_text(encoding="utf-8")
        return self.parse_text(text, resolved)

    def parse_text(self, text: str, path: Path) -> MdcDocument:
        lines = text.splitlines()
        if not lines or lines[0].strip() != "---":
            raise TeamLoaderError(f"{path} must start with YAML frontmatter.")
        end_index = self._find_frontmatter_end(lines, path)
        frontmatter_text = "\n".join(lines[1:end_index])
        body = "\n".join(lines[end_index + 1:]).lstrip("\n")
        frontmatter = self._yaml_parser.parse(frontmatter_text)
        if not isinstance(frontmatter, dict):
            raise TeamLoaderError(f"{path} frontmatter must be a YAML mapping.")
        return MdcDocument(path=path, frontmatter=frontmatter, body=body)

    def _find_frontmatter_end(self, lines: list[str], path: Path) -> int:
        for index in range(1, len(lines)):
            if lines[index].strip() == "---":
                return index
        raise TeamLoaderError(f"{path} is missing the closing frontmatter separator.")
