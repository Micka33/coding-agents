from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.team_instanciator.dotenv_loader import DotEnvLoader


class DotEnvLoaderTests(unittest.TestCase):
    def test_load_returns_empty_for_missing_file_and_parses_supported_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text(
                "\n".join(
                    [
                        "# comment",
                        "export API_KEY=plain # trailing comment",
                        "SINGLE='quoted # kept'",
                        'DOUBLE="line\\nvalue"',
                        "NO_SEPARATOR",
                        "=no-key",
                        "HASH=value#kept",
                        "SPACED=value # removed",
                    ]
                ),
                encoding="utf-8",
            )

            values = DotEnvLoader().load(path)

        self.assertEqual(DotEnvLoader().load("/missing/.env"), {})
        self.assertEqual(
            values,
            {
                "API_KEY": "plain",
                "SINGLE": "quoted # kept",
                "DOUBLE": "line\nvalue",
                "HASH": "value#kept",
                "SPACED": "value",
            },
        )

    def test_without_comment_respects_single_and_double_quoted_hashes(self) -> None:
        loader = DotEnvLoader()

        self.assertEqual(loader._without_comment("'#kept' # removed"), "'#kept' ")
        self.assertEqual(loader._without_comment('"#kept" # removed'), '"#kept" ')


if __name__ == "__main__":
    unittest.main()
