import { prettyJson } from "./utils.js";

export function visibleAgents(data, selectedColumnIds, tempRunIds, taskRunCache) {
  const selected = selectedColumnIds || new Set(defaultColumnIds(data));
  const options = columnOptions(data);
  const agents = [];

  (data?.agents || []).forEach((agent) => {
    if (selected.has(agent.id)) agents.push(agent);
  });

  options.forEach((option) => {
    if (option.kind === "task-agent-group" && selected.has(option.id)) {
      agents.push(taskAgentGroupAsAgent(option, taskRunCache));
    }
  });

  tempRunIds.forEach((runId) => {
    const run = taskRunCache.get(runId);
    if (run) agents.push(runAsAgent(run));
  });
  return agents;
}

export function columnOptions(data) {
  const options = (data?.agents || []).map((agent) => ({
    id: agent.id,
    name: agent.name,
    shortName: agent.shortName || agent.name,
    kind: agent.kind || "resident",
    stats: agent.stats || {},
    runIds: [],
    runCount: 0,
  }));

  const taskGroups = new Map();
  (data?.taskRuns || []).forEach((run) => {
    const agentName = taskAgentName(run);
    const id = taskAgentColumnId(agentName);
    if (!taskGroups.has(id)) {
      taskGroups.set(id, {
        id,
        name: agentName,
        shortName: agentName,
        kind: "task-agent-group",
        stats: emptyStats(),
        runIds: [],
        runCount: 0,
      });
    }
    const option = taskGroups.get(id);
    option.runIds.push(run.id);
    option.runCount += 1;
    option.stats = addStats(option.stats, run.stats || {});
  });

  return [...options, ...taskGroups.values()];
}

export function defaultColumnIds(data) {
  return (data?.agents || []).map((agent) => agent.id);
}

export function reconcileSelectedColumnIds(data, selectedColumnIds) {
  if (selectedColumnIds === null) return new Set(defaultColumnIds(data));
  const available = new Set(columnOptions(data).map((option) => option.id));
  return new Set([...selectedColumnIds].filter((id) => available.has(id)));
}

export function taskAgentColumnId(agentName) {
  return `task-agent:${agentName || "agent"}`;
}

export function isTaskAgentColumnId(id) {
  return String(id || "").startsWith("task-agent:");
}

export function selectedTaskRunIds(data, selectedColumnIds) {
  const selected = selectedColumnIds || new Set(defaultColumnIds(data));
  return columnOptions(data)
    .filter((option) => option.kind === "task-agent-group" && selected.has(option.id))
    .flatMap((option) => option.runIds);
}

function taskAgentGroupAsAgent(option, taskRunCache) {
  const loadedRuns = option.runIds.map((runId) => taskRunCache.get(runId)).filter((run) => run?.messages);
  const messages = loadedRuns.flatMap((run, index) => runMessagesWithSessionMarker(run, index));
  const loadedCount = loadedRuns.length;
  const runLabel = `${option.runCount} session${option.runCount > 1 ? "s" : ""}`;
  const loadingLabel = loadedCount < option.runCount ? ` · ${loadedCount}/${option.runCount} chargées` : "";

  return {
    id: option.id,
    name: option.name,
    shortName: option.shortName || option.name,
    threadId: `${runLabel}${loadingLabel}`,
    messages,
    kind: "task-agent-group",
    accent: "disposable",
    exists: true,
    stats: option.stats,
    runIds: option.runIds,
  };
}

function runMessagesWithSessionMarker(run, index) {
  const firstMessage = run.messages?.[0];
  const marker = {
    id: `${run.id}:session-marker`,
    index: -1,
    agentId: run.targetAgent || "agent",
    type: "session",
    name: `Session ${index + 1}`,
    toolCallId: null,
    contentText: run.preview || run.checkpointNs || run.id,
    blocks: [
      {
        type: "text",
        phase: run.shortName || run.targetAgent || "agent",
        text: `${run.checkpointNs || run.id}\n${run.preview || ""}`.trim(),
      },
    ],
    toolCalls: [],
    timestamp: firstMessage?.timestamp || { iso: null, epochMs: null },
    usage: null,
    responseMetadata: null,
    rawType: "SessionMarker",
  };

  return [
    marker,
    ...(run.messages || []).map((message) => ({
      ...message,
      id: `${run.id}:${message.id || message.index}`,
      sourceRunId: run.id,
    })),
  ];
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

function taskAgentName(run) {
  return String(run.targetAgent || run.shortName || run.name || "agent").replace(/^Run\s+/i, "").trim() || "agent";
}

function emptyStats() {
  return {
    messages: 0,
    toolCalls: 0,
    residentAgentCalls: 0,
    disposableAgentCalls: 0,
    thinkingBlocks: 0,
  };
}

function addStats(left, right) {
  const stats = { ...emptyStats(), ...left };
  Object.keys(emptyStats()).forEach((key) => {
    stats[key] = (stats[key] || 0) + (right[key] || 0);
  });
  return stats;
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
