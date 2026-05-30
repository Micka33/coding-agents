from __future__ import annotations

from pathlib import Path
from typing import Any

from .agent_definition import AgentDefinition
from .agent_reference import AgentReference
from .mdc_parser import MdcParser
from .team_definition import TeamDefinition
from .team_defaults import TeamDefaults
from .team_loader_error import TeamLoaderError
from .team_validator import TeamValidator
from .template_renderer import TemplateRenderer
from .yaml_parser import YamlParser


class TeamLoader:
    def __init__(
        self,
        yaml_parser: YamlParser | None = None,
        mdc_parser: MdcParser | None = None,
        template_renderer: TemplateRenderer | None = None,
        validator: TeamValidator | None = None,
    ) -> None:
        self._yaml_parser = yaml_parser or YamlParser()
        self._mdc_parser = mdc_parser or MdcParser(self._yaml_parser)
        self._template_renderer = template_renderer or TemplateRenderer()
        self._validator = validator or TeamValidator()

    def load(self, team_file: str | Path, variables: dict[str, Any] | None = None) -> TeamDefinition:
        path = Path(team_file).resolve()
        raw_mapping = self._load_team_mapping(path)
        base_variables = TeamDefaults.from_mapping(raw_mapping.get("defaults")).template_variables()
        config_variables = {**base_variables, **(variables or {})}
        mapping = self._template_renderer.render_config_value(raw_mapping, config_variables)
        references = self._load_agent_references(mapping)
        default_variables = TeamDefinition.from_mapping(path, mapping, {}).defaults.template_variables()
        template_variables = {**default_variables, **(variables or {})}
        agents = self._load_agents(path, references, template_variables)
        team = TeamDefinition.from_mapping(path, mapping, agents)
        self._validator.validate(team)
        return team

    def _load_team_mapping(self, path: Path) -> dict[str, Any]:
        if not path.is_file():
            raise TeamLoaderError(f"Team file does not exist: {path}")
        parsed = self._yaml_parser.parse(path.read_text(encoding="utf-8"))
        if not isinstance(parsed, dict):
            raise TeamLoaderError(f"{path} must contain a YAML mapping.")
        return parsed

    def _load_agent_references(self, mapping: dict[str, Any]) -> dict[str, AgentReference]:
        agents = mapping.get("agents")
        if not isinstance(agents, dict):
            raise TeamLoaderError("team.yaml requires an agents mapping.")
        return {agent_id: AgentReference.from_mapping(agent_id, value) for agent_id, value in agents.items()}

    def _load_agents(
        self,
        team_file: Path,
        references: dict[str, AgentReference],
        variables: dict[str, Any],
    ) -> dict[str, AgentDefinition]:
        agents: dict[str, AgentDefinition] = {}
        for agent_id, reference in references.items():
            config_path = reference.config_path(team_file)
            document = self._mdc_parser.parse_file(config_path)
            prompt_variables = self._agent_variables(document.frontmatter, variables)
            prompt = self._template_renderer.render(document.body, prompt_variables, config_path)
            agents[agent_id] = AgentDefinition.from_document(reference, document, prompt, prompt_variables)
        return agents

    def _agent_variables(self, frontmatter: dict[str, Any], variables: dict[str, Any]) -> dict[str, Any]:
        result = dict(variables)
        agent_variables = frontmatter.get("variables", {})
        if isinstance(agent_variables, dict):
            for key, value in agent_variables.items():
                if isinstance(value, str):
                    result[key] = self._template_renderer.render_config_string(value, result)
                else:
                    result[key] = value
        return result
