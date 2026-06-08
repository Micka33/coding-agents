from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.team_loader.models.agent_reference import AgentReference
from src.team_loader.models.checkpointer_default import CheckpointerDefault
from src.team_loader.models.custom_tool_definition import CustomToolDefinition
from src.team_loader.parsing.include_resolver import IncludeResolver
from src.team_loader.parsing.mdc_parser import MdcParser
from src.team_loader.models.team_definition import TeamDefinition
from src.team_loader.loading.team_loader import TeamLoader
from src.team_loader.errors.team_loader_error import TeamLoaderError
from src.team_loader.parsing.template_renderer import TemplateRenderer
from src.team_loader.models.tool_reference import ToolReference
from tests.support import agent


class ModelsAndRenderingTests(unittest.TestCase):
    def test_agent_reference_paths_checkpointer_defaults_custom_tools_and_tool_references(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            team_file = Path(tmp) / "team.yaml"
            reference = AgentReference.from_mapping(
                "entry",
                {
                    "kind": "deepagent",
                    "config": "agents/entry.mdc",
                    "entrypoint": True,
                    "enable_general_purpose_subagent": True,
                },
            )

            self.assertEqual(reference.config_path(team_file), (Path(tmp) / "agents" / "entry.mdc").resolve())
            self.assertTrue(reference.enable_general_purpose_subagent)

        checkpointer = CheckpointerDefault.from_mapping({"postgres_url": {"env": "DATABASE_URL"}})
        self.assertEqual(checkpointer.postgres_url_env, ("DATABASE_URL",))
        self.assertEqual(CustomToolDefinition.from_mapping("bad", {"args": "ignored", "exposes": "ignored"}).args, {})
        CustomToolDefinition("probe", "module:function", {}, ("one",)).validate_returned_tools(("one",))
        with self.assertRaisesRegex(ValueError, "missing: one; extra: two"):
            CustomToolDefinition("probe", "module:function", {}, ("one",)).validate_returned_tools(("two",))

        self.assertEqual(ToolReference.from_value("ls").name, "ls")
        self.assertEqual(ToolReference.from_value({"custom": "probe"}).custom, "probe")
        with self.assertRaisesRegex(TeamLoaderError, "Invalid tool reference"):
            ToolReference.from_value({"name": "ls"})

    def test_include_resolver_expands_nested_includes_and_reports_missing_or_recursive_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "base.md"
            first = root / "first.md"
            second = root / "second.md"
            base.write_text("A {{ include:first.md }} Z", encoding="utf-8")
            first.write_text("B {{ include:second.md }}", encoding="utf-8")
            second.write_text("C", encoding="utf-8")

            self.assertEqual(IncludeResolver().resolve(base.read_text(encoding="utf-8"), base), "A B C Z")

            with self.assertRaisesRegex(TeamLoaderError, "does not exist"):
                IncludeResolver().resolve("{{ include:missing.md }}", base)

            first.write_text("{{ include:second.md }}", encoding="utf-8")
            second.write_text("{{ include:first.md }}", encoding="utf-8")
            with self.assertRaisesRegex(TeamLoaderError, "Recursive include"):
                IncludeResolver().resolve("{{ include:first.md }}", base)

    def test_mdc_parser_success_and_error_cases(self) -> None:
        parser = MdcParser()
        document = parser.parse_text("---\nname: Entry\n---\n\nPrompt", Path("entry.mdc"))

        self.assertEqual(document.frontmatter, {"name": "Entry"})
        self.assertEqual(document.body, "Prompt")
        with self.assertRaisesRegex(TeamLoaderError, "must start"):
            parser.parse_text("name: Entry", Path("entry.mdc"))
        with self.assertRaisesRegex(TeamLoaderError, "frontmatter must be"):
            parser.parse_text("---\n- one\n---\nPrompt", Path("entry.mdc"))
        with self.assertRaisesRegex(TeamLoaderError, "missing the closing"):
            parser.parse_text("---\nname: Entry", Path("entry.mdc"))

    def test_template_renderer_handles_variables_config_values_and_includes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "base.md"
            include = Path(tmp) / "part.md"
            base.write_text("base", encoding="utf-8")
            include.write_text("included {{ name }}", encoding="utf-8")
            renderer = TemplateRenderer()

            self.assertEqual(renderer.render("A {{ include:part.md }} {{ missing }} {{ empty }}", {"name": "Ada", "empty": None}, base), "A included Ada {{ missing }} ")
            self.assertEqual(
                renderer.render_config_value({"items": ["hello {name}", None], "raw": 3}, {"name": "Ada"}),
                {"items": ["hello Ada", None], "raw": 3},
            )
            self.assertEqual(renderer.render_config_string("{missing} {empty}", {"empty": None}), "{missing} ")

    def test_team_definition_and_loader_cover_happy_path_and_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agents_dir = root / "agents"
            agents_dir.mkdir()
            (agents_dir / "entry.mdc").write_text(
                "---\nname: Entry\nvariables:\n  greeting: Hello {name}\n  count: 2\n---\n{{ greeting }} {{ count }} {{ missing }}",
                encoding="utf-8",
            )
            (agents_dir / "worker.mdc").write_text(
                "---\nschema_version: 1\n---\nWorker prompt",
                encoding="utf-8",
            )
            team_file = root / "team.yaml"
            team_file.write_text(
                "\n".join(
                    [
                        "schema_version: 1",
                        "id: product",
                        "conversation:",
                        "  human_input:",
                        "    default_targets:",
                        "      - entry",
                        "agents:",
                        "  Entry:",
                        "    kind: deepagent",
                        "    config: agents/entry.mdc",
                        "    entrypoint: true",
                        "    enable_general_purpose_subagent: true",
                        "    conversation: {}",
                        "  Worker:",
                        "    kind: deepagent",
                        "    config: agents/worker.mdc",
                        "relations:",
                        "  - from: entry",
                        "    to: worker",
                        "    relation: tool",
                        "    tool_name: ask_worker",
                    ]
                ),
                encoding="utf-8",
            )

            loaded = TeamLoader().load(team_file, {"name": "Ada"})

            self.assertEqual(loaded.entrypoint().prompt, "Hello Ada 2 {{ missing }}")
            self.assertEqual(loaded.agents["Entry"].variables["count"], 2)
            self.assertTrue(loaded.agents["Entry"].enable_general_purpose_subagent)
            self.assertEqual(loaded.conversation.human_input.default_targets, ("Entry",))
            self.assertEqual((loaded.relations[0].source, loaded.relations[0].target), ("Entry", "Worker"))
            self.assertEqual(loaded.agent_references["Entry"].conversation.aliases, ())
            self.assertIsNone(TeamDefinition.from_mapping(Path("team.yaml"), {"schema_version": 1, "id": "empty"}, {"worker": agent("worker")}).entrypoint())
            with self.assertRaisesRegex(TeamLoaderError, "does not exist"):
                TeamLoader()._load_team_mapping(root / "missing.yaml")
            list_file = root / "list.yaml"
            list_file.write_text("- one\n", encoding="utf-8")
            with self.assertRaisesRegex(TeamLoaderError, "must contain"):
                TeamLoader()._load_team_mapping(list_file)
            with self.assertRaisesRegex(TeamLoaderError, "requires an agents mapping"):
                TeamLoader()._load_agent_references({})


if __name__ == "__main__":
    unittest.main()
