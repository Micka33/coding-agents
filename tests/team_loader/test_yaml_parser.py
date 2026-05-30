from __future__ import annotations

import unittest

from src.team_loader.errors.team_loader_error import TeamLoaderError
from src.team_loader.parsing.yaml_parser import YamlParser


class YamlParserTests(unittest.TestCase):
    def test_parse_handles_empty_mapping_scalars_lists_folded_and_literal_blocks(self) -> None:
        parser = YamlParser()

        self.assertEqual(parser.parse(""), {})
        self.assertEqual(
            parser.parse(
                """
none: null
tilde: ~
truthy: true
falsey: FALSE
quoted: "hello"
negative: -3
folded: >
  one
  two

  three
literal: |
  alpha

  beta
empty:
items:
  - name:
    value: 1
  - https://example.test
empty_dict: {}
empty_list: []
""".strip()
            ),
            {
                "none": None,
                "tilde": None,
                "truthy": True,
                "falsey": False,
                "quoted": "hello",
                "negative": -3,
                "folded": "one two\n\nthree",
                "literal": "alpha\n\nbeta",
                "empty": None,
                "items": [{"name": None, "value": 1}, "https://example.test"],
                "empty_dict": {},
                "empty_list": [],
            },
        )

    def test_parse_reports_unexpected_content_indentation_and_bad_keys(self) -> None:
        parser = YamlParser()

        with self.assertRaisesRegex(TeamLoaderError, "Unexpected YAML content"):
            parser.parse("- one\nkey: value\n")
        with self.assertRaisesRegex(TeamLoaderError, "Unexpected indentation"):
            parser.parse("a:\n    b: 1\n  c: 2\n")
        with self.assertRaisesRegex(TeamLoaderError, "Expected YAML key/value"):
            parser.parse("bad\n")
        with self.assertRaisesRegex(TeamLoaderError, "Empty YAML key"):
            parser.parse(": value\n")

    def test_private_block_helpers_handle_lower_indent_mapping_breaks_and_short_literal_lines(self) -> None:
        parser = YamlParser()
        parser._lines = ["root: value"]
        self.assertEqual(parser._parse_block(0, 2), ({}, 0))

        parser._lines = ["- one"]
        self.assertEqual(parser._parse_mapping(0, 0), ({}, 0))
        self.assertEqual(parser._parse_list(0, 2), ([], 0))

        parser._lines = ["-", "-", "  name: nested"]
        self.assertEqual(parser._parse_list(0, 0), ([None, {"name": "nested"}], 3))

        parser._lines = ["x"]
        self.assertEqual(parser._line_without_common_indent(0, 10), "")


if __name__ == "__main__":
    unittest.main()
