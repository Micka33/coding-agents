import { prettyJson } from "./utils.js";

export function visibleAgents(data, tempRunIds, taskRunCache) {
  const agents = [...(data?.agents || [])];
  tempRunIds.forEach((runId) => {
    const run = taskRunCache.get(runId);
    if (run) agents.push(runAsAgent(run));
  });
  return agents;
}

export function runAsAgent(run) {
  return {
    ...run,
    id: run.id,
    name: run.name || `Run ${run.targetAgent || "agent"}`,
    shortName: run.shortName || run.targetAgent || "Run",
    threadId: `${run.threadId} / ${run.checkpointNs}`,
    messages: run.messages || [],
    kind: "disposable-run",
    accent: "disposable",
  };
}

export function buildTaskRunMap(data, taskRunCache) {
  const byId = new Map();
  (data?.taskRuns || []).forEach((run) => byId.set(run.id, run));
  taskRunCache.forEach((run, id) => byId.set(id, run));
  return byId;
}

export function buildResultMaps(agents) {
  const resultMaps = new Map();
  agents.forEach((agent) => {
    const byToolCallId = new Map();
    agent.messages.forEach((message) => {
      if (message.type === "tool" && message.toolCallId) {
        byToolCallId.set(message.toolCallId, message);
      }
    });

    const pairedToolResultIds = new Set();
    agent.messages.forEach((message) => {
      message.toolCalls.forEach((call) => {
        const result = byToolCallId.get(call.id);
        if (result) pairedToolResultIds.add(result.id);
      });
    });

    resultMaps.set(agent.id, { byToolCallId, pairedToolResultIds });
  });
  return resultMaps;
}

export function renderableMessages(agent, maps, search) {
  const normalizedSearch = search.trim().toLowerCase();
  return agent.messages.filter((message) => {
    if (maps?.pairedToolResultIds.has(message.id)) return false;
    if (!normalizedSearch) return true;
    return searchableText(message, maps).toLowerCase().includes(normalizedSearch);
  });
}

export function buildTimelineRows(agents, resultMaps, search) {
  const rows = new Map();
  let noTimestampOrder = 0;

  agents.forEach((agent) => {
    const maps = resultMaps.get(agent.id);
    renderableMessages(agent, maps, search).forEach((message) => {
      const epochMs = message.timestamp?.epochMs;
      const key = epochMs
        ? String(Math.floor(epochMs / 1000) * 1000)
        : `missing:${String(noTimestampOrder++).padStart(6, "0")}`;
      if (!rows.has(key)) {
        rows.set(key, {
          key,
          epochMs: epochMs ? Math.floor(epochMs / 1000) * 1000 : null,
          byAgent: new Map(),
        });
      }
      const row = rows.get(key);
      if (!row.byAgent.has(agent.id)) row.byAgent.set(agent.id, []);
      row.byAgent.get(agent.id).push(message);
    });
  });

  return [...rows.values()].sort((a, b) => {
    if (a.epochMs && b.epochMs) return a.epochMs - b.epochMs;
    if (a.epochMs) return -1;
    if (b.epochMs) return 1;
    return a.key.localeCompare(b.key);
  });
}

export function searchableText(message, maps) {
  const parts = [message.contentText, message.name, message.rawType];
  message.blocks.forEach((block) => parts.push(block.text, block.summary, block.phase));
  message.toolCalls.forEach((call) => {
    parts.push(call.name, call.kind, call.targetAgent, prettyJson(call.args));
    const result = maps?.byToolCallId.get(call.id);
    if (result) parts.push(result.contentText);
  });
  return parts.filter(Boolean).join("\n");
}
