import { fetchState, fetchTaskRun } from "./api.js";
import { collectElements, renderControls, setStatus } from "./controls.js";
import {
  buildResultMaps,
  buildTaskRunMap,
  columnOptions,
  reconcileSelectedColumnIds,
  selectedTaskRunIds,
  visibleAgents,
} from "./data.js";
import { renderRunDrawer } from "./drawer.js";
import { renderLayout } from "./layouts.js";
import { handleDetailsToggle } from "./messageList.js";
import { resetColumnSelection, resetRunState, setFormatMarkdown, state } from "./state.js";
import { capturePinnedScrollers, formatTime, restorePinnedScrollers } from "./utils.js";

const els = collectElements();

init();

function init() {
  els.app.addEventListener("toggle", (event) => handleDetailsToggle(event, state.openDetails), true);
  els.app.addEventListener("click", handleActionClick, true);
  els.drawerRoot.addEventListener("toggle", (event) => handleDetailsToggle(event, state.openDetails), true);
  els.drawerRoot.addEventListener("click", handleActionClick, true);
  els.columnPicker.addEventListener("click", handleColumnPickerClick);

  els.viewButtons.forEach((button) => {
    button.addEventListener("click", () => {
      state.view = button.dataset.view;
      render();
    });
  });

  els.threadSelect.addEventListener("change", () => {
    state.selectedThreadId = els.threadSelect.value;
    resetColumnSelection();
    loadState({ preserveScroll: false });
  });

  els.agentSelect.addEventListener("change", () => {
    state.selectedAgentId = els.agentSelect.value;
    render();
  });

  els.syncToggle.addEventListener("change", () => {
    state.syncScroll = els.syncToggle.checked;
    render();
  });

  els.liveToggle.addEventListener("change", () => {
    state.live = els.liveToggle.checked;
    schedulePolling();
  });

  els.markdownToggle.addEventListener("change", () => {
    setFormatMarkdown(els.markdownToggle.checked);
    render();
  });

  els.searchInput.addEventListener("input", () => {
    state.search = els.searchInput.value.trim().toLowerCase();
    render({ preserveScroll: false });
  });

  els.refreshButton.addEventListener("click", () => loadState({ refreshRuns: true }));
  loadState({ preserveScroll: false });
  schedulePolling();
}

function schedulePolling() {
  if (state.pollTimer) {
    clearInterval(state.pollTimer);
    state.pollTimer = null;
  }
  if (!state.live) {
    setStatus(els, "Live en pause");
    return;
  }
  state.pollTimer = setInterval(() => loadState(), 1800);
}

async function loadState(options = {}) {
  if (state.loading) return;
  state.loading = true;

  const preserveScroll = options.preserveScroll !== false;
  const firstLoad = state.data === null || !preserveScroll;
  const previousThreadId = state.data?.activeThreadId || null;

  try {
    const payload = await fetchState(state.selectedThreadId);
    state.data = payload;
    state.selectedThreadId = payload.activeThreadId;
    if (previousThreadId && previousThreadId !== payload.activeThreadId) {
      resetRunState();
      resetColumnSelection();
    }
    state.selectedColumnIds = reconcileSelectedColumnIds(payload, state.selectedColumnIds);

    await refreshSelectedAgentRuns(Boolean(options.refreshRuns));
    await refreshOpenRuns(Boolean(options.refreshRuns));
    const pinned = preserveScroll ? capturePinnedScrollers() : new Map();
    render({ pinned, firstLoad });

    const generated = payload.generatedAt?.epochMs
      ? formatTime(payload.generatedAt.epochMs)
      : "maintenant";
    setStatus(els, `À jour: ${generated}`);
  } catch (error) {
    setStatus(els, error.message, true);
  } finally {
    state.loading = false;
  }
}

async function refreshOpenRuns(force) {
  const runIds = new Set([...state.tempRunIds]);
  if (state.drawerRunId) runIds.add(state.drawerRunId);
  if (!force && !runIds.size) return;

  await Promise.all(
    [...runIds].map((runId) => ensureTaskRunLoaded(runId, { force }).catch(() => null)),
  );
}

async function refreshSelectedAgentRuns(force) {
  const runIds = selectedTaskRunIds(state.data, state.selectedColumnIds).filter((runId) => {
    return force || !state.taskRunCache.get(runId)?.messages;
  });
  if (!runIds.length) return;
  await Promise.all(runIds.map((runId) => ensureTaskRunLoaded(runId, { force }).catch(() => null)));
}

function render(options = {}) {
  if (!state.data) return;

  const preserveScroll = options.preserveScroll !== false;
  const pinned = preserveScroll ? options.pinned || capturePinnedScrollers() : new Map();
  const firstLoad = options.firstLoad || !preserveScroll;
  const optionsForColumns = columnOptions(state.data);
  const agents = visibleAgents(state.data, state.selectedColumnIds, state.tempRunIds, state.taskRunCache);

  if (!agents.some((agent) => agent.id === state.selectedAgentId)) {
    state.selectedAgentId = agents[0]?.id || "manager";
  }

  const resultMaps = buildResultMaps(agents);
  const context = {
    activeRunId: state.activeRunId,
    openDetails: state.openDetails,
    search: state.search,
    formatMarkdown: state.formatMarkdown,
    tempRunIds: state.tempRunIds,
    taskRunById: buildTaskRunMap(state.data, state.taskRunCache),
  };

  renderControls(els, state, agents, optionsForColumns);
  renderLayout(els, agents, resultMaps, state, context);
  renderRunDrawer(els, state, context);
  restorePinnedScrollers(pinned, firstLoad);
}

async function handleColumnPickerClick(event) {
  const button = event.target.closest("[data-column-id]");
  if (!button) return;

  const columnId = button.dataset.columnId;
  const next = new Set(state.selectedColumnIds || []);
  if (next.has(columnId)) next.delete(columnId);
  else next.add(columnId);

  state.selectedColumnIds = next;
  if (!next.has(state.selectedAgentId)) {
    state.selectedAgentId = [...next][0] || "";
  }

  render();
  await refreshSelectedAgentRuns(false);
  render();
}

async function handleActionClick(event) {
  const target = event.target.closest("[data-action]");
  if (!target) return;

  const action = target.dataset.action;
  const runId = target.dataset.runId;
  event.preventDefault();
  event.stopPropagation();

  if (action === "open-run-drawer" && runId) {
    await openRunDrawer(runId);
  } else if (action === "close-run-drawer") {
    closeRunDrawer();
  } else if (action === "open-run-column" && runId) {
    await openRunColumn(runId);
  } else if (action === "close-run-column" && runId) {
    closeRunColumn(runId);
  }
}

async function openRunDrawer(runId) {
  state.drawerRunId = runId;
  state.activeRunId = runId;
  render();
  await ensureTaskRunLoaded(runId);
  if (state.drawerRunId === runId) render();
}

function closeRunDrawer() {
  state.drawerRunId = null;
  if (!state.tempRunIds.includes(state.activeRunId)) state.activeRunId = null;
  render();
}

async function openRunColumn(runId) {
  await ensureTaskRunLoaded(runId);
  if (!state.tempRunIds.includes(runId)) state.tempRunIds.push(runId);
  state.activeRunId = runId;
  state.view = "columns";
  render();
}

function closeRunColumn(runId) {
  state.tempRunIds = state.tempRunIds.filter((candidate) => candidate !== runId);
  if (state.selectedAgentId === runId) state.selectedAgentId = "manager";
  if (state.activeRunId === runId && state.drawerRunId !== runId) state.activeRunId = null;
  render();
}

async function ensureTaskRunLoaded(runId, options = {}) {
  if (!options.force && state.taskRunCache.get(runId)?.messages) {
    return state.taskRunCache.get(runId);
  }
  if (state.taskRunPromises.has(runId)) return state.taskRunPromises.get(runId);

  const promise = fetchTaskRun(state.selectedThreadId, runId)
    .then((payload) => {
      if (payload.activeThreadId === state.selectedThreadId) {
        state.taskRunCache.set(runId, payload.run);
      }
      return payload.run;
    })
    .finally(() => state.taskRunPromises.delete(runId));

  state.taskRunPromises.set(runId, promise);
  return promise;
}
