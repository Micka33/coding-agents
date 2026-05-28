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
    threadId: agent.threadId,
    stats: agent.stats || {},
    runIds: [],
    runCount: 0,
  }));

  const taskGroups = new Map();
  (data?.runtimeLanes || [])
    .filter((lane) => lane.kind === "task-subagent-type")
    .forEach((lane) => {
      const agentName = taskLaneAgentName(lane);
      const id = lane.id || lane.laneId || taskAgentColumnId(agentName);
      taskGroups.set(id, {
        id,
        name: agentName,
        shortName: agentName,
        kind: "task-agent-group",
        stats: emptyStats(),
        runIds: [],
        runCount: 0,
        matchNames: taskLaneMatchNames(lane),
      });
    });

  (data?.taskRuns || []).forEach((run) => {
    const agentName = taskAgentName(run);
    const id = taskGroupIdForRun(taskGroups, agentName);
    if (!taskGroups.has(id)) {
      taskGroups.set(id, {
        id,
        name: agentName,
        shortName: agentName,
        kind: "task-agent-group",
        stats: emptyStats(),
        runIds: [],
        runCount: 0,
        matchNames: new Set([agentName]),
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
  return columnOptions(data)
    .filter((option) => option.kind !== "task-agent-group" || option.runCount > 0)
    .map((option) => option.id);
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
  const messages = run.messages || [];
  const firstMessage = messages[0];
  const inputIndex = messages.findIndex((message) => message.type === "human");
  const inputMessage = inputIndex >= 0 ? messages[inputIndex] : null;
  const promptText = inputMessage?.contentText || run.preview || "";
  const sourceLabel = run.sourceAgent ? `Appel de ${run.sourceAgent}` : `Session ${index + 1}`;
  const targetLabel = run.targetAgent || run.shortName || "agent";
  const marker = {
    id: `${run.id}:session-marker`,
    index: -1,
    agentId: targetLabel,
    type: "session",
    name: sourceLabel,
    toolCallId: null,
    contentText: [sourceLabel, targetLabel, promptText, run.checkpointNs || run.id].filter(Boolean).join("\n"),
    blocks: [],
    toolCalls: [],
    timestamp: firstMessage?.timestamp || { iso: null, epochMs: null },
    usage: null,
    responseMetadata: null,
    rawType: "TaskRunMarker",
    sourceAgent: run.sourceAgent,
    targetAgent: targetLabel,
    promptText,
    checkpointNs: run.checkpointNs || run.id,
  };

  return [
    marker,
    ...messages.filter((_, messageIndex) => messageIndex !== inputIndex).map((message) => ({
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

function taskLaneAgentName(lane) {
  return String(lane.agentName || lane.agentId || lane.targetAgentId || "agent").trim() || "agent";
}

function taskLaneMatchNames(lane) {
  return new Set(
    [lane.agentId, lane.agentName, lane.targetAgentId]
      .map((value) => String(value || "").trim())
      .filter(Boolean),
  );
}

function taskGroupIdForRun(taskGroups, agentName) {
  const normalized = String(agentName || "").trim();
  for (const [id, group] of taskGroups) {
    if (group.matchNames?.has(normalized)) return id;
  }
  return taskAgentColumnId(agentName);
}

function emptyStats() {
  return {
    messages: 0,
    toolCalls: 0,
    residentAgentCalls: 0,
    disposableAgentCalls: 0,
    thinkingBlocks: 0,
    cost: emptyCost(),
  };
}

function addStats(left, right) {
  const stats = { ...emptyStats(), ...left };
  ["messages", "toolCalls", "residentAgentCalls", "disposableAgentCalls", "thinkingBlocks"].forEach((key) => {
    stats[key] = (stats[key] || 0) + (right[key] || 0);
  });
  stats.cost = addCosts(stats.cost, right.cost);
  return stats;
}

function emptyCost() {
  return {
    estimated_cost_usd: 0,
    estimated_cost_usd_decimal: "0",
    partial: false,
    calls_with_usage: 0,
    messages_without_usage: 0,
    priced_calls: 0,
    unpriced_calls: 0,
    unbucketed_calls: 0,
    tokens: {
      input: 0,
      input_uncached: 0,
      input_cached: 0,
      output: 0,
      reasoning_output: 0,
    },
    subtotals_usd: {
      input: "0",
      cached_input: "0",
      output: "0",
    },
    time_series: {
      hour: [],
      day: [],
      week: [],
    },
    by_model: [],
    unpriced_models: [],
  };
}

function addCosts(left, right) {
  const cost = cloneCost(left || emptyCost());
  const incoming = right || emptyCost();
  cost.pricing_version = cost.pricing_version || incoming.pricing_version;
  cost.currency = cost.currency || incoming.currency;
  cost.tier = cost.tier || incoming.tier;
  cost.estimated_cost_usd += Number(incoming.estimated_cost_usd || 0);
  cost.estimated_cost_usd_decimal = String(cost.estimated_cost_usd);
  cost.partial = Boolean(cost.partial || incoming.partial);
  cost.calls_with_usage += incoming.calls_with_usage || 0;
  cost.messages_without_usage += incoming.messages_without_usage || 0;
  cost.priced_calls += incoming.priced_calls || 0;
  cost.unpriced_calls += incoming.unpriced_calls || 0;
  cost.unbucketed_calls += incoming.unbucketed_calls || 0;
  mergeTokenCounts(cost.tokens, incoming.tokens || {});
  mergeCostParts(cost.subtotals_usd, incoming.subtotals_usd || {});
  cost.time_series = mergeTimeSeries(cost.time_series, incoming.time_series || {});
  cost.by_model = mergeModelCosts(cost.by_model, incoming.by_model || []);
  cost.unpriced_models = mergeUnpricedModels(cost.unpriced_models, incoming.unpriced_models || []);
  return cost;
}

function cloneCost(cost) {
  return {
    ...emptyCost(),
    ...cost,
    tokens: { ...emptyCost().tokens, ...(cost.tokens || {}) },
    subtotals_usd: { ...emptyCost().subtotals_usd, ...(cost.subtotals_usd || {}) },
    time_series: cloneTimeSeries(cost.time_series || {}),
    by_model: [...(cost.by_model || [])],
    unpriced_models: [...(cost.unpriced_models || [])],
  };
}

function cloneTimeSeries(timeSeries) {
  return {
    hour: [...(timeSeries.hour || [])],
    day: [...(timeSeries.day || [])],
    week: [...(timeSeries.week || [])],
  };
}

function mergeTokenCounts(target, source) {
  Object.keys(emptyCost().tokens).forEach((key) => {
    target[key] = (target[key] || 0) + (source[key] || 0);
  });
}

function mergeCostParts(target, source) {
  Object.keys(emptyCost().subtotals_usd).forEach((key) => {
    target[key] = String(Number(target[key] || 0) + Number(source[key] || 0));
  });
}

function mergeModelCosts(left, right) {
  const byModel = new Map((left || []).map((model) => [model.priced_model || model.model, { ...model }]));
  (right || []).forEach((model) => {
    const key = model.priced_model || model.model;
    const current = byModel.get(key) || {
      ...model,
      calls: 0,
      estimated_cost_usd: 0,
      estimated_cost_usd_decimal: "0",
      tokens: { ...emptyCost().tokens },
      subtotals_usd: { ...emptyCost().subtotals_usd },
    };
    current.calls = (current.calls || 0) + (model.calls || 0);
    current.estimated_cost_usd = Number(current.estimated_cost_usd || 0) + Number(model.estimated_cost_usd || 0);
    current.estimated_cost_usd_decimal = String(current.estimated_cost_usd);
    mergeTokenCounts(current.tokens, model.tokens || {});
    mergeCostParts(current.subtotals_usd, model.subtotals_usd || {});
    byModel.set(key, current);
  });
  return [...byModel.values()].sort((a, b) => Number(b.estimated_cost_usd || 0) - Number(a.estimated_cost_usd || 0));
}

function mergeUnpricedModels(left, right) {
  const byModel = new Map((left || []).map((model) => [model.model, { ...model }]));
  (right || []).forEach((model) => {
    const key = model.model || "unknown";
    const current = byModel.get(key) || { model: key, calls: 0, error: model.error };
    current.calls += model.calls || 0;
    byModel.set(key, current);
  });
  return [...byModel.values()].sort((a, b) => (b.calls || 0) - (a.calls || 0));
}

function mergeTimeSeries(left, right) {
  const merged = cloneTimeSeries(left || {});
  ["hour", "day", "week"].forEach((granularity) => {
    const byBucket = new Map((merged[granularity] || []).map((bucket) => [bucket.bucket, cloneBucket(bucket)]));
    (right[granularity] || []).forEach((bucket) => {
      const key = bucket.bucket || "";
      if (!key) return;
      const current = byBucket.get(key) || {
        bucket: key,
        label: bucket.label || key,
        estimated_cost_usd: 0,
        estimated_cost_usd_decimal: "0",
        calls: 0,
        tokens: { ...emptyCost().tokens },
      };
      current.estimated_cost_usd = Number(current.estimated_cost_usd || 0) + Number(bucket.estimated_cost_usd || 0);
      current.estimated_cost_usd_decimal = String(current.estimated_cost_usd);
      current.calls = (current.calls || 0) + (bucket.calls || 0);
      mergeTokenCounts(current.tokens, bucket.tokens || {});
      byBucket.set(key, current);
    });
    merged[granularity] = [...byBucket.values()].sort((a, b) => String(a.bucket).localeCompare(String(b.bucket)));
  });
  return merged;
}

function cloneBucket(bucket) {
  return {
    ...bucket,
    tokens: { ...emptyCost().tokens, ...(bucket.tokens || {}) },
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
    renderableMessages(agent, maps, search).filter(isTimelineMessage).forEach((message) => {
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

function isTimelineMessage(message) {
  return message.rawType !== "ConversationMarker";
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
