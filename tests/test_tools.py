from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from coding_agents.tools import default_tools, fetch_url, web_search


class TavilyToolRegistrationTests(unittest.TestCase):
    def test_default_tools_register_web_search_and_fetch_url(self) -> None:
        self.assertEqual([tool.name for tool in default_tools()], ["web_search", "fetch_url"])

    def test_web_search_caps_max_results_and_compacts_content(self) -> None:
        client = Mock()
        client.search.return_value = {
            "query": "python runtime",
            "answer": "answer",
            "results": [
                {
                    "title": "Result",
                    "url": "https://example.test/runtime",
                    "content": "c" * 4_100,
                    "raw_content": "r" * 12_100,
                    "score": 0.9,
                    "published_date": "2026-05-25",
                }
            ],
        }

        with patch("coding_agents.tools._tavily_client", return_value=client):
            result = web_search.invoke(
                {
                    "query": "python runtime",
                    "max_results": 999,
                    "include_raw_content": True,
                }
            )

        client.search.assert_called_once()
        self.assertEqual(client.search.call_args.kwargs["max_results"], 10)
        compact = result["results"][0]
        self.assertEqual(result["query"], "python runtime")
        self.assertLessEqual(len(compact["content"]), 4_020)
        self.assertLessEqual(len(compact["raw_content"]), 12_020)
        self.assertTrue(compact["content"].endswith("...[truncated]"))
        self.assertTrue(compact["raw_content"].endswith("...[truncated]"))

    def test_fetch_url_compacts_results_and_preserves_failed_results(self) -> None:
        client = Mock()
        client.extract.return_value = {
            "results": [
                {
                    "url": "https://example.test/page",
                    "raw_content": "x" * 12_100,
                    "images": ["https://example.test/image.png"],
                }
            ],
            "failed_results": [{"url": "https://example.test/missing", "error": "404"}],
        }

        with patch("coding_agents.tools._tavily_client", return_value=client):
            result = fetch_url.invoke(
                {
                    "url": "https://example.test/page",
                    "query": "only relevant details",
                    "extract_depth": "advanced",
                    "format": "text",
                }
            )

        client.extract.assert_called_once_with(
            urls="https://example.test/page",
            query="only relevant details",
            extract_depth="advanced",
            format="text",
        )
        self.assertEqual(result["results"][0]["url"], "https://example.test/page")
        self.assertLessEqual(len(result["results"][0]["raw_content"]), 12_020)
        self.assertEqual(result["results"][0]["images"], ["https://example.test/image.png"])
        self.assertEqual(result["failed_results"], [{"url": "https://example.test/missing", "error": "404"}])


if __name__ == "__main__":
    unittest.main()
