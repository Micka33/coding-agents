# Deep Agents Tool Visibility Recommendation

## Problem

Deep Agents injects built-in tools such as `ls`, `read_file`, `glob`, `grep`,
`write_file`, `edit_file`, `execute`, and `task` independently of this
project's agent `toolsets`.

Today, an agent can see and call a built-in tool even when its declared
toolsets do not grant the corresponding capability. The operation is then
blocked by the filesystem permission layer. This is safe as a backstop, but it
creates poor agent behavior: the agent is invited to use a tool that will fail.

The Hayashi-Razan file access issue is an example:

- the user attached or referenced a file;
- Hayashi-Razan saw filesystem tools and attempted to use them;
- the runtime denied the read because the agent did not have
  `scoped_read_tools`;
- the agent reported that file access was denied.

## Recommendation

Separate tool visibility from tool permission.

Tool visibility should decide which tools the model is allowed to see. Tool
permission should remain as a safety backstop if an unavailable operation still
reaches the tool layer.

For this recommendation, "provided to an agent" means "included in the tool
list sent to the model." Deep Agents may still keep filesystem middleware in
the graph as required scaffolding, but unavailable tools must be removed from
the model request before the model can choose them.

## Proposed Implementation

Add a per-agent middleware that filters Deep Agents built-in tools before the
model request is sent.

Suggested capability groups:

```python
READ_TOOLS = {"ls", "read_file", "glob", "grep"}
WRITE_TOOLS = {"write_file", "edit_file"}
SHELL_TOOLS = {"execute"}
DELEGATION_TOOLS = {"task"}
```

Suggested rules:

- Hide `READ_TOOLS` unless the agent has `scoped_read_tools`.
- Hide `WRITE_TOOLS` unless the agent has `write`.
- Hide `SHELL_TOOLS` unless the agent has `shell` and the runtime has a usable
  shell backend.
- Hide `task` unless the team intentionally exposes subagents for that agent.

`task` is a tool at the model boundary and should be filtered by the same
visibility middleware. It should not be modeled as a normal `toolsets` entry,
because its valid targets come from team topology rather than from a reusable
tool bundle.

Implement this with a local middleware rather than importing Deep Agents'
private `_ToolExclusionMiddleware`.

The middleware should:

- inspect `request.tools`;
- remove tools whose names are in a computed built-in exclusion set;
- leave all other tools unchanged;
- run late enough that tools injected by Deep Agents middleware are already
  present.

The exclusion set should be computed from `AgentDefinition.toolsets`, team
relations, and the resolved runtime backend.

Keep `PermissionsFactory` unchanged as the defensive layer:

- deny reads unless the agent has `scoped_read_tools`;
- deny writes unless the agent has `write`.

## Factory Wiring

Wire tool visibility in the factories that create Deep Agents.

For top-level Deep Agents, `DeepAgentFactory.create()` should pass the
visibility middleware through `create_deep_agent(middleware=...)`.
`ToolsetResolver.resolve_for_deepagents()` is not the right place for this:
Deep Agents injects its built-in tools after this project resolves additional
tools.

For declarative Deep Agents subagents, `SubagentFactory.create()` should include
the subagent's own visibility middleware and permissions in the returned
subagent spec. Subagents should not inherit the parent agent's read/write
visibility by accident.

LangChain-backed subagents do not need this middleware because they do not get
Deep Agents built-in filesystem tools. They already receive only the tools
selected by `ToolsetResolver.resolve_for_langchain()`.

## Documentation Updates

When implementing this change, update `docs/team_yaml.md` alongside the code.

The `team.yaml` documentation should describe:

- `agents.<id>.enable_general_purpose_subagent`;
- the default value of `false`;
- that the setting is valid only for `kind: deepagent`;
- that declared `relation: subagent` entries expose only those declared
  subagents and do not enable the default `general-purpose` subagent;
- how built-in Deep Agents tools are hidden from the model unless the agent has
  the corresponding capability.

## `task` And Default Subagents

The `task` tool needs separate handling because Deep Agents may auto-add a
default `general-purpose` subagent.

For strict team-defined capabilities, the runtime should expose delegation only
when the team declares a `relation: subagent` from the agent, or when the agent
explicitly opts into the default `general-purpose` subagent. The default
`general-purpose` subagent should not silently create a `task` capability.

Recommended `team.yaml` shape:

```yaml
agents:
  Francis-Bacon:
    kind: deepagent
    config: ./agents/francis-bacon.mdc
    enable_general_purpose_subagent: true
```

Default behavior:

- `enable_general_purpose_subagent` is `false` when omitted;
- the config is valid only for `kind: deepagent`;
- if the config is present on non-Deep Agents, validation should fail rather
  than silently ignore it.

Recommended behavior:

- if the agent has no declared subagent relations, hide `task`;
- if the agent has declared subagent relations, expose `task` only for those
  declared subagents;
- expose the default `general-purpose` subagent only when that agent explicitly
  sets `enable_general_purpose_subagent: true`;
- declaring a relation to a custom subagent, such as `translator`, must not
  implicitly enable access to the default `general-purpose` subagent.

If Deep Agents does not offer a per-call way to disable the default
`general-purpose` subagent, prefer hiding `task` over relying on permission
errors. A follow-up implementation may need an app-level harness-profile
registration to disable the default subagent consistently, with per-agent
opt-in adding it back through explicit subagent specs.

## Custom Tools

Do not hide custom tools by default.

Custom tools are already selected through declared toolsets. If an agent does
not list the toolset containing a custom tool, that custom tool is not passed to
`create_deep_agent()`.

The visibility middleware should therefore filter known Deep Agents built-ins,
not arbitrary user-provided tools.

One guard is still useful: reject or warn when a custom tool exposes a name that
collides with a Deep Agents built-in tool, such as `read_file` or `glob`.
Collisions make tool visibility ambiguous.

Suggested validation:

- reject custom tools whose names collide with Deep Agents built-ins;
- keep selected non-colliding custom tools visible;
- do not infer read/write policy for custom tools in this change.

## Attachment Delivery

Tool visibility alone prevents the agent from being shown unusable filesystem
tools. It does not decide what Studio should do when a user attaches or
references a file and targets an agent that lacks read capability.

Studio should append the message. It should not block the message or fail
delivery solely because a targeted agent lacks `scoped_read_tools`.

Reason: an agent may have user-provided custom tools that can consume
attachment content by attachment id, URI, or some other custom interface. The
runtime should not assume `scoped_read_tools` is the only possible attachment
access path.

Recommended behavior:

- append human messages with attachments or workspace references;
- keep selected custom tools visible;
- hide built-in read tools from agents without `scoped_read_tools`;
- surface attachment metadata in model-visible context;
- include built-in filesystem read paths only for agents that have
  `scoped_read_tools`.

If an agent has no visible way to read an attachment, it may still respond that
it cannot access the content, but it should not be shown built-in read tools
that are guaranteed to fail.

## Out Of Scope

Do not implement custom tool-level policy yet.

For example, do not add metadata such as:

```yaml
custom_tools:
  repo_reader:
    capabilities:
      - read
```

That may become useful later, especially for custom tools that read files or
call privileged APIs, but it is not required to fix the current built-in tool
visibility problem.

## Success Criteria

- An agent without `scoped_read_tools` does not see `ls`, `read_file`, `glob`,
  or `grep`.
- An agent without `scoped_read_tools` still cannot read if a read call reaches
  the permission layer.
- An agent with `scoped_read_tools` sees read tools and can read files under
  the resolved runtime root.
- An agent without `write` does not see `write_file` or `edit_file`.
- Selected custom tools remain visible to agents that declare the corresponding
  custom toolset.
- A file-attachment scenario does not result in the model being shown unusable
  file tools.
- A file-attachment scenario targeting an agent without `scoped_read_tools`
  still appends and delivers the message.
- Attachment metadata is model-visible, while built-in filesystem read paths
  are shown only to agents with `scoped_read_tools`.
- The default Deep Agents `general-purpose` subagent is unavailable by default
  and becomes available only through explicit per-agent
  `enable_general_purpose_subagent: true` opt-in.
