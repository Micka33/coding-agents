# First-Class MCP Tools In `team.yaml`

## Goal

Add first-class MCP server support to `team.yaml` so agents can use tools from
local or hosted MCP servers without writing Python custom-tool factories.

Success criteria:

- Teams can declare MCP servers in `team.yaml`.
- Toolsets can reference MCP servers directly.
- `exposes` is optional; omitted means expose all server tools.
- Local stdio MCP servers and remote HTTP MCP servers are supported.
- Common authentication patterns are configurable without storing secrets in
  `team.yaml`.
- Existing `custom_tools` behavior remains backward-compatible.

## Proposed YAML Shape

### Local stdio server

Use the public `mcp-server-time` reference server as the documentation example.
It exposes `get_current_time` and `convert_time`.

```yaml
mcp_servers:
  time:
    transport: stdio
    command: uvx
    args:
      - mcp-server-time

toolsets:
  time:
    - mcp: time
```

Because `exposes` is omitted, all tools advertised by the server are exposed to
agents that request the `time` toolset.

### Remote hosted server with bearer auth

```yaml
mcp_servers:
  company_docs:
    transport: http
    url: https://mcp.example.com/mcp
    auth:
      type: bearer
      env: COMPANY_DOCS_MCP_TOKEN
    headers:
      X-Tenant:
        env: COMPANY_TENANT_ID
      X-Client: coding-agents
    exposes:
      - search_docs
      - fetch_doc

toolsets:
  docs:
    - mcp: company_docs
```

When `exposes` is present, it is an allowlist. Only the named MCP tools are
visible to agents.

## Semantics

- `mcp_servers` is a top-level mapping.
- Each key under `mcp_servers` is a stable server id.
- Toolsets reference a server with `{mcp: server_id}`.
- `exposes` is optional.
- Missing `exposes` means expose every tool returned by the MCP server.
- Present `exposes` means expose only those tool names.
- Toolsets remain the agent-level authorization boundary: an agent only receives
  MCP tools from toolsets listed in its `.mdc` frontmatter.
- Tool names must be checked for collisions after all built-in, custom,
  relation, and MCP tools are resolved for an agent. Any duplicate final tool
  name fails instantiation.

## Transport Support

Supported transports:

| Transport | Required fields | Optional fields |
| --- | --- | --- |
| `stdio` | `command` | `args`, `env`, `cwd` |
| `http` | `url` | `headers`, `auth`, `timeout` |
| `streamable_http` | `url` | `headers`, `auth`, `timeout` |
| `sse` | `url` | `headers`, `auth`, `timeout` |

Prefer documenting `http` / `streamable_http` for hosted servers. Accept `sse`
for compatibility, but do not make it the recommended path.

`http` is user-facing shorthand for `streamable_http`. The loader should accept
both and canonicalize `http` to the adapter's streamable HTTP transport value
internally.

`timeout` is expressed in seconds. The default is `30`.

For `stdio`, configured `env` values are merged over the runtime/process
environment. They do not replace the entire environment.

## Authentication

Do not put secret values directly in examples. Prefer environment/runtime config
references.

### Bearer token

```yaml
auth:
  type: bearer
  env: MCP_TOKEN
```

Runtime behavior:

- Read `MCP_TOKEN` from runtime configuration or environment.
- Add `Authorization: Bearer <token>`.
- Fail instantiation if the token is required and missing.

### API key header

```yaml
auth:
  type: api_key
  header: X-API-Key
  env: MCP_API_KEY
```

Runtime behavior:

- Read `MCP_API_KEY` from runtime configuration or environment.
- Add `<header>: <key>`.
- Fail instantiation if the key is required and missing.

### Static and env-backed headers

```yaml
headers:
  X-Client: coding-agents
  X-Tenant:
    env: COMPANY_TENANT_ID
```

Header values can be either strings or `{env: NAME}` references.

### Custom auth escape hatch

```yaml
auth:
  type: custom
  factory: my_package.auth:create_httpx_auth
  args:
    audience: docs
```

`factory` must use `module:function` format. The function is called as:

```python
def create_httpx_auth(context, args):
    ...
```

`context` should expose the runtime configuration/environment view, matching the
custom-tool context pattern where practical. The function should return an auth
object compatible with the MCP adapter's HTTP client path.

Full OAuth should not be included in the first implementation. OAuth needs a
login flow, refresh handling, storage, and likely CLI or Studio UI support.

## Loader Model Changes

Add a model such as `McpServerDefinition` with fields:

- `id: str`
- `transport: str`
- `command: str | None`
- `args: tuple[str, ...]`
- `url: str | None`
- `env: dict[str, McpConfigValue]`
- `headers: dict[str, McpConfigValue]`
- `auth: McpAuthDefinition | None`
- `timeout: int | None`
- `cwd: str | None`
- `exposes: tuple[str, ...] | None`

Important distinction:

- `exposes is None`: expose all server tools.
- `exposes == ()`: invalid if explicitly configured as an empty list.

Extend `ToolReference` so it accepts:

```yaml
- mcp: time
```

and keeps existing support for:

```yaml
- web_search
- custom: scoped_read_tools
```

## Runtime Changes

Add an `McpToolFactory` that:

1. Builds the MCP client configuration from `McpServerDefinition`.
2. Resolves env-backed headers/auth through `RuntimeConfiguration`.
3. Uses `langchain-mcp-adapters` to load MCP tools as LangChain `BaseTool`s.
4. Applies `exposes` filtering only when `exposes` is present.
5. Raises a clear instantiation error if required auth config is missing.
6. Raises a clear instantiation error if an explicit `exposes` tool is not
   returned by the server.
7. Caches resolved tools per MCP server id for the duration of one team
   instantiation.
8. Fails instantiation if the final tool list for an agent contains duplicate
   tool names.

`ToolsetResolver` should resolve MCP references alongside built-ins and custom
tools. Deep Agents can receive the resulting LangChain `BaseTool`s the same way
custom tools are currently passed through.

MCP tools should be loaded once per server id during a team instantiation and
then reused for every agent/toolset that references that server. Do not create a
new MCP client per agent unless a future server type requires agent-specific
context.

## Dependency Changes

Add `langchain-mcp-adapters` to project dependencies.

Keep using LangChain tools as the integration boundary. The project already uses
Deep Agents as the orchestration layer and LangChain `BaseTool`s as the shared
tool primitive, so MCP should plug in at the tool-source layer.

## Validation

Loader-time validation:

- `mcp_servers.<id>.transport` must be supported.
- `stdio` requires `command`.
- HTTP-style transports require `url`.
- `auth.type` must be one of the supported auth modes.
- `{mcp: server_id}` references must point to a declared server.
- Explicit empty `exposes: []` is invalid.

Instantiation-time validation:

- Required environment/runtime config values must be present.
- The MCP server must be reachable.
- Explicit `exposes` entries must match returned tool names.
- Final agent tool names must not collide.
- Tool resolution should respect the per-instantiation MCP server cache.

## Tests

Add focused tests for:

- Parsing `mcp_servers` definitions.
- Optional vs explicit-empty `exposes`.
- Tool reference parsing for `{mcp: id}`.
- Validator errors for missing server references and invalid transport config.
- Header and auth env resolution.
- HTTP transport canonicalization from `http` to `streamable_http`.
- Default timeout behavior.
- Stdio env merge behavior.
- Custom auth factory signature and error handling.
- Filtering explicit `exposes`.
- Exposing all tools when `exposes` is omitted.
- Per-instantiation caching of tools by MCP server id.
- Tool collision detection after MCP tools are resolved.

Use fake MCP client/tool factory seams in unit tests. Avoid requiring a live MCP
server in the core test suite.

## Documentation Updates

Update `docs/team_yaml.md` with:

- The `mcp_servers` top-level key.
- The local `mcp-server-time` example.
- A remote HTTP server example with bearer auth.
- The `exposes` default behavior.
- A note that local stdio MCP servers execute commands declared by trusted team
  configuration.
- A note that secrets should come from environment/runtime configuration.

References:

- LangChain MCP adapter docs: https://docs.langchain.com/oss/python/langchain/mcp
- MCP reference servers: https://github.com/modelcontextprotocol/servers
