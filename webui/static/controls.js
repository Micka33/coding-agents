import { escapeAttr, escapeHtml, formatCost, formatTime } from "./utils.js";

export function collectElements() {
  return {
    app: document.querySelector("#app"),
    drawerRoot: document.querySelector("#drawerRoot"),
    dbPath: document.querySelector("#dbPath"),
    columnPicker: document.querySelector("#columnPicker"),
    threadSelect: document.querySelector("#threadSelect"),
    threadCostButton: document.querySelector("#threadCostButton"),
    pricingTierSelect: document.querySelector("#pricingTierSelect"),
    agentSelect: document.querySelector("#agentSelect"),
    syncToggle: document.querySelector("#syncToggle"),
    liveToggle: document.querySelector("#liveToggle"),
    markdownToggle: document.querySelector("#markdownToggle"),
    themeToggle: document.querySelector("#themeToggle"),
    searchInput: document.querySelector("#searchInput"),
    refreshButton: document.querySelector("#refreshButton"),
    status: document.querySelector("#status"),
    viewButtons: [...document.querySelectorAll("[data-view]")],
  };
}

export function renderControls(els, state, agents, columnOptions) {
  els.dbPath.textContent = state.data?.dbPath || "";

  const currentThreadOptions = state.data?.threads || [];
  els.threadSelect.innerHTML = currentThreadOptions
    .map((thread) => {
      const updated = thread.updatedAt?.epochMs ? formatTime(thread.updatedAt.epochMs) : "sans date";
      return `<option value="${escapeAttr(thread.id)}">${escapeHtml(thread.id)} · ${escapeHtml(updated)}</option>`;
    })
    .join("");
  if (state.selectedThreadId) els.threadSelect.value = state.selectedThreadId;
  renderThreadCostButton(els, state);
  renderPricingTierSelect(els, state);

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
  els.markdownToggle.checked = state.formatMarkdown;
  els.themeToggle.checked = state.theme === "dark";
  renderColumnPicker(els, state, columnOptions);
}

export function setStatus(els, text, isError = false) {
  els.status.textContent = text || "";
  els.status.classList.toggle("error", isError);
}

function renderColumnPicker(els, state, options) {
  const selected = state.selectedColumnIds || new Set();
  const chips = (options || [])
    .map((option) => {
      const active = selected.has(option.id);
      const count = option.kind === "task-agent-group" ? `${option.runCount} runs` : `${option.stats?.messages || 0} msg`;
      return `
        <button
          class="agent-chip ${active ? "active" : ""}"
          type="button"
          data-column-id="${escapeAttr(option.id)}"
          aria-pressed="${active ? "true" : "false"}"
          title="${escapeAttr(option.name)}"
        >
          <span class="agent-chip-name">${escapeHtml(option.name)}</span>
          <span class="agent-chip-count">${escapeHtml(count)}</span>
        </button>
      `;
    })
    .join("");

  els.columnPicker.innerHTML = `
    <span class="column-picker-label">Colonnes</span>
    <div class="agent-chips">${chips || `<span class="empty-chip">Aucun agent</span>`}</div>
  `;
}

function renderThreadCostButton(els, state) {
  const cost = state.data?.cost;
  els.threadCostButton.textContent = formatCost(cost);
  els.threadCostButton.title = cost?.partial
    ? "Estimation de coût partielle du thread"
    : "Estimation de coût du thread";
  els.threadCostButton.classList.toggle("partial", Boolean(cost?.partial));
}

function renderPricingTierSelect(els, state) {
  const tiers = state.data?.pricing?.availableTiers || ["standard", "batch", "flex", "priority"];
  els.pricingTierSelect.innerHTML = tiers
    .map((tier) => `<option value="${escapeAttr(tier)}">${escapeHtml(tier)}</option>`)
    .join("");
  els.pricingTierSelect.value = state.data?.pricing?.tier || state.pricingTier || "standard";
}
