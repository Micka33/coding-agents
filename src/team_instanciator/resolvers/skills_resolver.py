from src.team_loader.models.agent_definition import AgentDefinition
from src.team_loader.models.team_definition import TeamDefinition

from src.team_instanciator.configuration.runtime_configuration import RuntimeConfiguration
from src.team_instanciator.resolvers.skill_source_resolver import SkillSourceResolver


class SkillsResolver:
    def __init__(
        self,
        configuration: RuntimeConfiguration | None = None,
        skill_source_resolver: SkillSourceResolver | None = None,
    ) -> None:
        self._skill_source_resolver = skill_source_resolver or SkillSourceResolver(configuration)

    def resolve(self, team: TeamDefinition, agent: AgentDefinition) -> list[tuple[str, str]] | None:
        if agent.skills is None:
            return None
        sources = self._skill_source_resolver.resolve_agent_sources(team, agent)
        if not sources:
            return None
        return [source.deepagents_source for source in sources]
