from __future__ import annotations

import unittest
from unittest.mock import patch

from langchain_core.tools import StructuredTool

from src.team_instanciator.custom_tool_factory import CustomToolFactory
from src.team_instanciator.team_instanciator_error import TeamInstanciatorError
from src.team_loader.custom_tool_definition import CustomToolDefinition


NOT_CALLABLE = "value"


def single_tool_factory(context, args):
    def ping() -> str:
        """Return pong."""

        return "pong"

    return StructuredTool.from_function(ping, name="ping")


def sequence_tool_factory(context, args):
    def ping() -> str:
        """Return pong."""

        return "pong"

    return [StructuredTool.from_function(ping, name="ping")]


def non_sequence_factory(context, args):
    return 42


def non_tool_sequence_factory(context, args):
    return ["not-a-tool"]


def one_argument_factory(context):
    return []


class CustomToolFactoryTests(unittest.TestCase):
    def test_load_factory_validates_path_import_attribute_and_callable(self) -> None:
        factory = CustomToolFactory()

        with self.assertRaisesRegex(TeamInstanciatorError, "Unsupported"):
            factory._load_factory("not-module-function")
        with self.assertRaisesRegex(TeamInstanciatorError, "Could not import"):
            factory._load_factory("missing.module:function")
        with self.assertRaisesRegex(TeamInstanciatorError, "not found"):
            factory._load_factory(f"{__name__}:missing")
        with self.assertRaisesRegex(TeamInstanciatorError, "not callable"):
            factory._load_factory(f"{__name__}:NOT_CALLABLE")

    def test_create_accepts_single_tool_and_sequence(self) -> None:
        single = CustomToolFactory().create(
            CustomToolDefinition(id="probe", factory=f"{__name__}:single_tool_factory", args={}, exposes=("ping",)),
            context=object(),
        )
        sequence = CustomToolFactory().create(
            CustomToolDefinition(id="probe", factory=f"{__name__}:sequence_tool_factory", args={}, exposes=("ping",)),
            context=object(),
        )

        self.assertEqual([tool.name for tool in single], ["ping"])
        self.assertEqual([tool.name for tool in sequence], ["ping"])

    def test_create_reports_bad_signature_return_shape_and_exposed_tool_mismatch(self) -> None:
        cases = [
            ("signature", f"{__name__}:one_argument_factory", ("ping",), "must accept"),
            ("non_sequence", f"{__name__}:non_sequence_factory", ("ping",), "must return"),
            ("non_tool", f"{__name__}:non_tool_sequence_factory", ("ping",), "non-tool"),
            ("mismatch", f"{__name__}:sequence_tool_factory", ("other",), "exposes mismatch"),
        ]

        for custom_id, factory_path, exposes, message in cases:
            with self.subTest(custom_id=custom_id), self.assertRaisesRegex(TeamInstanciatorError, message):
                CustomToolFactory().create(
                    CustomToolDefinition(id=custom_id, factory=factory_path, args={}, exposes=exposes),
                    context=object(),
                )

    def test_signature_validation_ignores_value_error_from_inspect(self) -> None:
        definition = CustomToolDefinition(id="probe", factory="module:function", args={}, exposes=())

        with patch("src.team_instanciator.custom_tool_factory.inspect.signature", side_effect=ValueError):
            CustomToolFactory()._validate_signature(definition, object(), object())


if __name__ == "__main__":
    unittest.main()
