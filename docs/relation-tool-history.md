# Relation Tool History

Status: design draft

Scope: `src/team_loader`, `src/team_instanciator`, `docs/team_yaml.md`,
`docs/agent_mdc.md`

## Summary

`relation: tool` currently creates `ask_*` tools that reuse a stable child
thread for the target agent. This is useful for resident collaborators, but it
does not fit one-shot reviewer or helper agents that should answer each call
without seeing previous `ask_*` messages.

Add a `history` field on tool relations:

```yaml
relations:
  - id: qa-review
    from: developer
    to: qa-engineer
    relation: tool
    tool_name: ask_qa_engineer
    history: disposable
    input_schema:
      message: string
```

`history: persistent` preserves the current behavior. `history: disposable`
starts each relation-tool call from a fresh target-agent thread.

## Goals

- Keep existing teams backward compatible.
- Let `ask_*` tools choose whether the target agent sees prior calls.
- Put the choice on the relation, because the same target agent may be
  persistent from one caller and disposable from another.
- Keep the implementation small and explicit.
- Avoid changing `relation: subagent` semantics.

## Non-Goals

- Do not make `state.persistence` control relation-tool history.
- Do not change public mention history.
- Do not change Deep Agents task/subagent delegation behavior.
- Do not introduce a broader state or memory policy system.

## Configuration

`relations[].history` is optional.

| Value | Behavior |
| --- | --- |
| `persistent` | Reuse the stable relation thread. This is the default and matches current behavior. |
| `disposable` | Use a fresh target-agent thread for each tool call. |

Example resident collaborator:

```yaml
relations:
  - id: product-advice
    from: engineering-manager
    to: product-analyst
    relation: tool
    tool_name: ask_product_analyst
    history: persistent
    input_schema:
      message: string
```

Example one-shot reviewer:

```yaml
relations:
  - id: qa-review
    from: developer
    to: qa-engineer
    relation: tool
    tool_name: ask_qa_engineer
    history: disposable
    input_schema:
      message: string
```

For `relation: subagent`, `history` should be omitted. Subagent delegation is a
different calling path and should not gain an unused field. If it is present on
a subagent relation, validation must fail with a message explaining that
subagent calls are already stateless task delegations and do not resume history
from one call to the next.

## Runtime Behavior

Current persistent relation tools derive a child thread from the parent thread,
relation id, and target agent:

```text
<parent_thread>:relation:<relation_id>:agent:<target_agent>
```

With `history: persistent`, keep that thread id unchanged.

With `history: disposable`, derive a child thread from the same relation context
plus the current tool call id:

```text
<parent_thread>:relation:<relation_id>:call:<tool_call_id>:agent:<target_agent>
```

If no tool call id is available, use the generated edge id already created by
`RelationTool.run`. The id only needs to be stable for the duration of that
single call.

The target agent still receives the same user message shape:

```python
{"messages": [{"role": "user", "content": message}]}
```

Only the child `thread_id` changes.

## Implementation Plan

### 1. Extend The Relation Model

Add `history: str | None` to `RelationDefinition`.

Keep an omitted field as `None` so validation can distinguish an omitted
subagent `history` from an explicit one:

```python
history=optional_string(mapping.get("history"))
```

For tool relations, the effective runtime value is `relation.history or
"persistent"`.

### 2. Validate At Load Time

In `TeamValidator._validate_relations`:

- accept only `persistent` and `disposable` for `relation: tool`;
- reject any explicit `history` value on `relation: subagent`.

The validation error for `history` on `relation: subagent` should explain the
behavior, not only name the invalid key:

```text
Relation developer->qa-engineer defines history, but history is only valid for
relation: tool. Subagent relations use task delegation; each invocation is
stateless and does not resume history from previous calls.
```

### 3. Add Thread Id Factory Support

Keep the existing `ThreadIdFactory.relation(...)` method unchanged.

Add a method for disposable relation calls:

```python
def disposable_relation(
    self,
    parent_thread_id: str,
    relation: RelationDefinition,
    call_id: str,
) -> str:
    relation_id = self._segment(self.relation_id(relation))
    call = self._segment(call_id)
    target = self._segment(relation.target)
    return f"{parent_thread_id}:relation:{relation_id}:call:{call}:agent:{target}"
```

### 4. Select The Thread In `RelationTool`

Move `edge_id` creation before child thread selection.

Then choose the thread id from `relation.history`:

```python
edge_id = self._tool_call_id(runtime) or f"edge_{uuid.uuid4().hex}"
history = self._relation.history or "persistent"
if history == "disposable":
    thread_id = self._thread_id_factory.disposable_relation(
        parent_thread_id,
        self._relation,
        edge_id,
    )
else:
    thread_id = self._thread_id_factory.relation(parent_thread_id, self._relation)
```

Keep the rest of the metadata recording intact. `relation_id`, target agent,
parent thread, child logical thread key, physical thread id, and tool-call edge
records remain useful for Studio and debugging.

### 5. Represent Disposable Runs In The Manifest And Studio

The manifest currently describes stable lanes. Persistent relation lanes should
stay as they are.

For disposable relation tools, keep one stable relation lane as the grouping
surface, but treat its child runs as dynamic call instances. This is the most
intuitive UI shape: users still see one `ask_qa_engineer` relation, with
separate call histories underneath it.

Implementation guidance:

- add relation history to runtime lane metadata so Studio can label the lane;
- for `history: persistent`, keep the existing `thread_id_pattern`;
- for `history: disposable`, do not expose one concrete `thread_id` for the
  lane, because no child thread exists until a tool call happens;
- use recorded `ToolCallEdge` rows to discover and display each disposable child
  run under the relation lane.

## Tests

Add focused tests for:

- `RelationDefinition.from_mapping` keeps omitted `history` distinguishable from
  explicit values.
- Tool relations use effective history `persistent` when `history` is omitted.
- `RelationDefinition.from_mapping` reads `history: disposable`.
- `TeamValidator` rejects invalid values such as `history: temporary`.
- `TeamValidator` rejects explicit `history` on `relation: subagent` and the
  message explains that subagent task calls are stateless.
- Persistent relation tools keep using the same child thread for repeated calls.
- Disposable relation tools use different child threads for repeated calls.
- Disposable relation tool calls are grouped under one relation lane but exposed
  as separate child call instances.
- Existing teams without `history` load unchanged.
- Documentation examples parse.

## Documentation Updates

Update `docs/team_yaml.md`:

- add `history` to the relation key table;
- explain that it applies to `relation: tool`;
- show `persistent` and `disposable` examples;
- state that `persistent` is the default.

Update `docs/agent_mdc.md`:

- clarify that `state.persistence` does not control `ask_*` history;
- point readers to `relations[].history` for relation-tool history.

## Migration

No migration is required.

Existing teams behave as if every tool relation declares:

```yaml
history: persistent
```

Teams that want stateless `ask_*` calls can opt in relation by relation.

## Decisions

- `history` must be rejected on `relation: subagent`.
- Studio should display disposable relation runs as dynamic call instances under
  the stable relation lane.
- The field name is `history`; it is the clearest term from the user's point of
  view and avoids confusion with checkpointer persistence.
