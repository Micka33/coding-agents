from __future__ import annotations

import json
import subprocess
import urllib.request
from pathlib import Path

from langchain_core.tools import StructuredTool

from src.team_instanciator.configuration.runtime_configuration import RuntimeConfiguration


class BuiltinToolFactory:
    def __init__(self, configuration: RuntimeConfiguration | None = None) -> None:
        self._configuration = configuration or RuntimeConfiguration()

    def create(self, name: str, root_dir: Path) -> StructuredTool:
        self._root_dir = root_dir.resolve()
        if name == "web_search":
            return StructuredTool.from_function(self.web_search, name="web_search", description="Search the web with Tavily when TAVILY_API_KEY is configured.")
        if name == "fetch_url":
            return StructuredTool.from_function(self.fetch_url, name="fetch_url", description="Fetch the textual contents of a URL.")
        if name == "write_file":
            return StructuredTool.from_function(self.write_file, name="write_file", description="Write text to a repository file.")
        if name == "edit_file":
            return StructuredTool.from_function(self.edit_file, name="edit_file", description="Replace text in a repository file.")
        if name == "execute":
            return StructuredTool.from_function(self.execute, name="execute", description="Run a local shell command.")
        raise KeyError(name)

    def web_search(self, query: str, max_results: int = 5) -> str:
        """Search the web with Tavily when TAVILY_API_KEY is configured."""

        api_key = self._configuration.tool_api_key("tavily")
        if not api_key:
            return json.dumps({"query": query, "max_results": max_results, "results": [], "note": "TAVILY_API_KEY is not configured."})
        try:
            from tavily import TavilyClient
        except ImportError:
            return json.dumps({"query": query, "max_results": max_results, "results": [], "error": "The tavily package is not installed."})
        client = TavilyClient(api_key=api_key)
        try:
            response = client.search(query=query, max_results=max_results, include_answer=True)
        except Exception as error:
            return json.dumps({"query": query, "max_results": max_results, "results": [], "error": str(error)})
        return json.dumps(response, ensure_ascii=False)

    def fetch_url(self, url: str, timeout: int = 20) -> str:
        """Fetch a URL using the Python standard library."""

        with urllib.request.urlopen(url, timeout=timeout) as response:
            data = response.read(500_000)
        return data.decode("utf-8", errors="replace")

    def write_file(self, path: str, content: str) -> str:
        """Write content to a file path."""

        target = self._safe_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"Wrote {target.relative_to(self._root_dir)}."

    def edit_file(self, path: str, old: str, new: str) -> str:
        """Replace the first occurrence of old text in a file."""

        target = self._safe_path(path)
        text = target.read_text(encoding="utf-8")
        if old not in text:
            return f"No occurrence found in {target.relative_to(self._root_dir)}."
        target.write_text(text.replace(old, new, 1), encoding="utf-8")
        return f"Edited {target.relative_to(self._root_dir)}."

    def execute(self, command: str, timeout: int = 120) -> str:
        """Run a local shell command."""

        result = subprocess.run(command, shell=True, text=True, capture_output=True, timeout=timeout, cwd=self._root_dir)
        return result.stdout + result.stderr

    def _safe_path(self, path: str) -> Path:
        target = (self._root_dir / path.lstrip("/")).resolve()
        target.relative_to(self._root_dir)
        return target
