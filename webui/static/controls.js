import { escapeAttr, escapeHtml, formatTime } from "./utils.js";

export function collectElements() {
  return {
    app: document.querySelector("#app"),
    drawerRoot: document.querySelector("#drawerRoot"),
    dbPath: document.querySelector("#dbPath"),
    threadSelect: document.querySelector("#threadSelect"),
    agentSelect: document.querySelector("#agentSelect"),
    syncToggle: document.querySelector("#syncToggle"),
    liveToggle: document.querySelector("#liveToggle"),
    searchInput: document.querySelector("#searchInput"),
    refreshButton: document.querySelector("#refreshButton"),
    status: document.querySelector("#status"),
    viewButtons: [...document.querySelectorAll("[data-view]")],
  };
}

export function renderControls(els, state, agents) {
  els.dbPath.textContent = state.data?.dbPath || "";

  const currentThreadOptions = state.data?.threads || [];
  els.threadSelect.innerHTML = currentThreadOptions
    .map((thread) => {
      const updated = thread.updatedAt?.epochMs ? formatTime(thread.updatedAt.epochMs) : "sans date";
      return `<option value="${escapeAttr(thread.id)}">${escapeHtml(thread.id)} · ${escapeHtml(updated)}</option>`;
    })
    .join("");
  if (state.selectedThreadId) els.threadSelect.value = state.selectedThreadId;

  els.agentSelect.innerHTML = agents
    .map((agent) => `<option value="${escapeAttr(agent.id)}">${escapeHtml(agent.name)}</option>`)
    .join("");
  els.agentSelect.value = state.selectedAgentId;

  els.viewButtons.forEach((button) => {
    button.classList.toggle("active", button.dataset.view === state.view);
  });

  document.querySelector(".agent-field").classList.toggle("hidden", state.view !== "single");
  els.syncToggle.disabled = state.view !== "columns" || !state.data?.hasTimestamps;
  if (els.syncToggle.disabled) state.syncScroll = false;
  els.syncToggle.checked = state.syncScroll;
  els.liveToggle.checked = state.live;
}

export function setStatus(els, text, isError = false) {
  els.status.textContent = text || "";
  els.status.classList.toggle("error", isError);
}
