from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.team_instanciator.factories.builtin_tool_factory import BuiltinToolFactory
from src.team_instanciator.configuration.runtime_configuration import RuntimeConfiguration


class UrlOpenResponse:
    def __enter__(self) -> UrlOpenResponse:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self, limit: int) -> bytes:
        return b"hello"


class FakeTavilyClient:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def search(self, **kwargs):
        return {"api_key": self.api_key, "kwargs": kwargs}


class RaisingTavilyClient:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def search(self, **kwargs):
        raise RuntimeError("network down")


class BuiltinToolFactoryTests(unittest.TestCase):
    def test_create_returns_known_tools_and_rejects_unknown_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            factory = BuiltinToolFactory()
            names = ["web_search", "fetch_url", "write_file", "edit_file", "execute"]

            tools = [factory.create(name, Path(tmp)) for name in names]

            self.assertEqual([tool.name for tool in tools], names)
            with self.assertRaises(KeyError):
                factory.create("missing", Path(tmp))

    def test_web_search_handles_missing_key_missing_package_errors_and_success(self) -> None:
        self.assertEqual(
            json.loads(BuiltinToolFactory().web_search("query")),
            {"query": "query", "max_results": 5, "results": [], "note": "TAVILY_API_KEY is not configured."},
        )

        real_import = __import__

        def import_without_tavily(name, *args, **kwargs):
            if name == "tavily":
                raise ImportError("missing")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=import_without_tavily):
            missing_package = json.loads(BuiltinToolFactory(RuntimeConfiguration({"TAVILY_API_KEY": "key"})).web_search("query", max_results=2))

        self.assertEqual(missing_package["error"], "The tavily package is not installed.")

        with patch.dict(sys.modules, {"tavily": SimpleNamespace(TavilyClient=RaisingTavilyClient)}):
            errored = json.loads(BuiltinToolFactory(RuntimeConfiguration({"TAVILY_API_KEY": "key"})).web_search("query"))
        self.assertEqual(errored["error"], "network down")

        with patch.dict(sys.modules, {"tavily": SimpleNamespace(TavilyClient=FakeTavilyClient)}):
            successful = json.loads(BuiltinToolFactory(RuntimeConfiguration({"TAVILY_API_KEY": "key"})).web_search("query", max_results=3))
        self.assertEqual(successful["api_key"], "key")
        self.assertEqual(successful["kwargs"]["max_results"], 3)

    def test_file_url_and_local_file_operations_are_scoped_to_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            factory = BuiltinToolFactory()
            factory.create("write_file", root)

            with patch("src.team_instanciator.factories.builtin_tool_factory.urllib.request.urlopen", return_value=UrlOpenResponse()):
                self.assertEqual(factory.fetch_url("https://example.test"), "hello")
            with patch("src.team_instanciator.factories.builtin_tool_factory.urllib.request.urlopen", side_effect=RuntimeError("HTTP Error 403: Forbidden")):
                fetch_error = json.loads(factory.fetch_url("https://blocked.example.test"))
            self.assertEqual(fetch_error["url"], "https://blocked.example.test")
            self.assertEqual(fetch_error["content"], "")
            self.assertEqual(fetch_error["error"], "HTTP Error 403: Forbidden")

            self.assertEqual(factory.write_file("/nested/file.txt", "alpha beta"), "Wrote nested/file.txt.")
            self.assertEqual((root / "nested" / "file.txt").read_text(encoding="utf-8"), "alpha beta")
            self.assertEqual(factory.edit_file("nested/file.txt", "beta", "gamma"), "Edited nested/file.txt.")
            self.assertEqual(factory.edit_file("nested/file.txt", "missing", "value"), "No occurrence found in nested/file.txt.")
            self.assertEqual(factory.execute("printf done"), "done")
            with self.assertRaises(ValueError):
                factory.write_file("../outside.txt", "outside")


if __name__ == "__main__":
    unittest.main()
