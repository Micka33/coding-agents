import { buildResultMaps, columnOptions, runAsAgent } from "./data.js";
import { clearMessagePaneHost, renderMessagePane, replacePanePart } from "./panes.js";
import { escapeAttr, escapeHtml, formatCompactNumber, formatCost } from "./utils.js";

export function renderRunDrawer(els, state, context, agents = []) {
  if (state.costBreakdown) {
    renderCostDrawer(els.drawerRoot, state, agents);
    return;
  }

  if (!state.drawerRunId) {
    clearMessagePaneHost(els.drawerRoot);
    document.body.classList.remove("drawer-open");
    return;
  }

  document.body.classList.add("drawer-open");
  const run = state.taskRunCache.get(state.drawerRunId);
  const summary = context.taskRunById.get(state.drawerRunId);
  const displayRun = run || summary;
  const shellMode = run?.messages ? "messages" : "loading";
  const agent = run?.messages ? runAsAgent(run) : null;
  const resultMaps = agent ? buildResultMaps([agent]) : new Map();

  renderMessagePane(els.drawerRoot, agent, agent ? resultMaps.get(agent.id) : null, context, {
    shellHtml: renderDrawerShell(displayRun, state),
    shellKey: `drawer:${state.drawerRunId}`,
    shellMode,
    scrollKey: `drawer:${state.drawerRunId}`,
    listSelector: ".drawer-message-list",
    showEmpty: true,
    updateChrome: (root) => updateDrawerChrome(root, displayRun, state),
  });
}

function renderDrawerShell(run, state) {
  const title = run?.name || "Run agent";
  const stats = run?.stats || {};
  const isColumnOpen = state.tempRunIds.includes(state.drawerRunId);
  const columnAction = isColumnOpen ? "close-run-column" : "open-run-column";
  const body = run?.messages
    ? `<div class="drawer-message-list message-list scroll-region" data-scroll-key="drawer:${escapeAttr(state.drawerRunId)}"></div>`
    : `<div class="empty-state">Chargement du run...</div>`;

  return `
    <div class="drawer-backdrop" data-action="close-run-drawer"></div>
    <aside class="run-drawer" role="dialog" aria-label="${escapeAttr(title)}">
      ${renderDrawerHeader(run, state)}
      ${renderDrawerToolbar(stats, state, columnAction, isColumnOpen)}
      <div class="drawer-body">
        ${body}
      </div>
    </aside>
  `;
}

function updateDrawerChrome(root, run, state) {
  const drawer = root.querySelector(".run-drawer");
  if (!drawer) return;

  const title = run?.name || "Run agent";
  const stats = run?.stats || {};
  const isColumnOpen = state.tempRunIds.includes(state.drawerRunId);
  const columnAction = isColumnOpen ? "close-run-column" : "open-run-column";

  drawer.setAttribute("aria-label", title);
  replacePanePart(drawer, ".drawer-header", renderDrawerHeader(run, state));
  replacePanePart(drawer, ".drawer-toolbar", renderDrawerToolbar(stats, state, columnAction, isColumnOpen));
}

function renderDrawerHeader(run, state) {
  const title = run?.name || "Run agent";
  return `
    <header class="drawer-header">
      <div class="lane-title">
        <h2>${escapeHtml(title)}</h2>
        <p>${escapeHtml(run?.checkpointNs || state.drawerRunId)}</p>
      </div>
      <button class="icon-button" type="button" data-action="close-run-drawer" title="Fermer" aria-label="Fermer">&times;</button>
    </header>
  `;
}

function renderDrawerToolbar(stats, state, columnAction, isColumnOpen) {
  return `
    <div class="drawer-toolbar">
      <button class="mini-button" type="button" data-action="${columnAction}" data-run-id="${escapeAttr(state.drawerRunId)}">
        ${isColumnOpen ? "Retirer la colonne" : "Ouvrir en colonne"}
      </button>
      ${renderDrawerCostButton(stats.cost, "column", state.drawerRunId)}
      <span class="run-metrics">${escapeHtml((stats.messages || 0) + " msg · " + (stats.toolCalls || 0) + " outils")}</span>
    </div>
  `;
}

function renderCostDrawer(root, state, agents) {
  document.body.classList.add("drawer-open");
  root.innerHTML = renderCostDrawerShell(state, agents);
  root.dataset.messagePaneKey = `cost:${state.costBreakdown.scope}:${state.costBreakdown.id || ""}`;
  root.dataset.messagePaneMode = "cost";
}

function renderCostDrawerShell(state, agents) {
  const target = resolveCostTarget(state, agents);
  const cost = target.cost || {};
  return `
    <div class="drawer-backdrop" data-action="close-cost-breakdown"></div>
    <aside class="run-drawer cost-drawer" role="dialog" aria-label="${escapeAttr(target.title)}">
      <header class="drawer-header">
        <div class="lane-title">
          <h2>${escapeHtml(target.title)}</h2>
          <p>${escapeHtml(target.subtitle)}</p>
        </div>
        <button class="icon-button" type="button" data-action="close-cost-breakdown" title="Fermer" aria-label="Fermer">&times;</button>
      </header>
      <div class="drawer-toolbar">
        <span class="cost-total">${escapeHtml(formatCost(cost))}</span>
        <span class="run-metrics">${escapeHtml(cost.tier || state.data?.pricing?.tier || "standard")} · ${escapeHtml(cost.currency || "USD")}</span>
        ${cost.partial ? `<span class="badge cost-warning">partiel</span>` : ""}
      </div>
      <div class="drawer-body cost-drawer-body">
        ${renderCostSummary(cost, state)}
        ${renderCostParts(cost)}
        ${renderCostSources(target.sources)}
        ${renderModelBreakdown(cost)}
        ${renderUnpricedModels(cost)}
      </div>
    </aside>
  `;
}

function resolveCostTarget(state, agents) {
  const target = state.costBreakdown || { scope: "thread" };
  if (target.scope === "column") {
    const agent = agents.find((candidate) => candidate.id === target.id)
      || columnOptions(state.data).find((candidate) => candidate.id === target.id);
    if (agent) {
      return {
        title: `Coût ${agent.shortName || agent.name}`,
        subtitle: agent.threadId || agent.name,
        cost: agent.stats?.cost,
        sources: sourceRowsForColumn(state, agent),
      };
    }
    const run = state.taskRunCache.get(target.id)
      || (state.data?.taskRuns || []).find((candidate) => candidate.id === target.id);
    if (run) {
      return {
        title: `Coût ${run.shortName || run.targetAgent || "run"}`,
        subtitle: run.checkpointNs || run.id,
        cost: run.stats?.cost,
        sources: [],
      };
    }
  }

  return {
    title: "Coût du thread",
    subtitle: state.data?.activeThreadId || "thread",
    cost: state.data?.cost,
    sources: sourceRowsForThread(state),
  };
}

function sourceRowsForThread(state) {
  return columnOptions(state.data).map((option) => ({
    id: option.id,
    label: option.name,
    detail: option.kind === "task-agent-group" ? `${option.runCount} sessions` : option.threadId || option.kind,
    cost: option.stats?.cost,
  }));
}

function sourceRowsForColumn(state, agent) {
  if (agent.kind !== "task-agent-group" || !agent.runIds?.length) return [];
  const runsById = new Map((state.data?.taskRuns || []).map((run) => [run.id, run]));
  return agent.runIds.map((runId, index) => {
    const run = runsById.get(runId);
    return {
      id: runId,
      label: run?.name || `Session ${index + 1}`,
      detail: run?.checkpointNs || runId,
      cost: run?.stats?.cost,
    };
  });
}

function renderDrawerCostButton(cost, scope, id) {
  if (!cost) return "";
  return `
    <button
      class="cost-pill inline-cost-pill${cost.partial ? " partial" : ""}"
      type="button"
      data-action="open-cost-breakdown"
      data-cost-scope="${escapeAttr(scope)}"
      data-cost-id="${escapeAttr(id)}"
    >
      ${escapeHtml(formatCost(cost))}
    </button>
  `;
}

function renderCostSummary(cost, state) {
  return `
    <section class="cost-section">
      <div class="cost-kpis">
        ${renderKpi("Estimé", formatCost(cost))}
        ${renderKpi("Appels tarifés", `${cost.priced_calls || 0}/${cost.calls_with_usage || 0}`)}
        ${renderKpi("Input", formatCompactNumber(cost.tokens?.input))}
        ${renderKpi("Output", formatCompactNumber(cost.tokens?.output))}
        ${renderKpi("Reasoning", formatCompactNumber(cost.tokens?.reasoning_output))}
        ${renderKpi("Sans usage", formatCompactNumber(cost.messages_without_usage))}
      </div>
      <p class="cost-note">
        Prix ${escapeHtml(state.data?.pricing?.version || cost.pricing_version || "inconnu")}.
        Les tokens de raisonnement sont affichés pour lecture, mais inclus dans les tokens output.
      </p>
    </section>
  `;
}

function renderCostParts(cost) {
  const rows = [
    ["Input non cache", cost.tokens?.input_uncached, cost.subtotals_usd?.input],
    ["Input cache", cost.tokens?.input_cached, cost.subtotals_usd?.cached_input],
    ["Output", cost.tokens?.output, cost.subtotals_usd?.output],
  ];
  return renderCostTable("Breakdown tokens", ["Poste", "Tokens", "Coût"], rows.map(([label, tokens, amount]) => [
    label,
    formatCompactNumber(tokens),
    formatUsd(amount),
  ]));
}

function renderCostSources(sources) {
  if (!sources?.length) return "";
  return renderCostTable("Breakdown sources", ["Source", "Détail", "Coût"], sources.map((source) => [
    source.label,
    source.detail || "",
    formatCost(source.cost),
  ]));
}

function renderModelBreakdown(cost) {
  const models = cost.by_model || [];
  if (!models.length) return "";
  return renderCostTable("Breakdown modèles", ["Modèle", "Appels", "Coût"], models.map((model) => [
    `${model.priced_model || model.model}${model.model && model.model !== model.priced_model ? ` (${model.model})` : ""}`,
    String(model.calls || 0),
    formatUsd(model.estimated_cost_usd_decimal),
  ]));
}

function renderUnpricedModels(cost) {
  const unpriced = cost.unpriced_models || [];
  if (!unpriced.length) return "";
  return renderCostTable("Non tarifé", ["Modèle", "Appels", "Raison"], unpriced.map((model) => [
    model.model || "inconnu",
    String(model.calls || 0),
    model.error || "Tarif absent",
  ]));
}

function renderKpi(label, value) {
  return `
    <div class="cost-kpi">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
    </div>
  `;
}

function renderCostTable(title, headers, rows) {
  return `
    <section class="cost-section">
      <h3>${escapeHtml(title)}</h3>
      <table class="cost-table">
        <thead>
          <tr>${headers.map((header) => `<th>${escapeHtml(header)}</th>`).join("")}</tr>
        </thead>
        <tbody>
          ${rows.map((row) => `
            <tr>${row.map((cell) => `<td>${escapeHtml(cell)}</td>`).join("")}</tr>
          `).join("")}
        </tbody>
      </table>
    </section>
  `;
}

function formatUsd(value) {
  const number = Number(value || 0);
  if (!Number.isFinite(number) || number === 0) return "$0.00";
  if (number < 0.01) return `$${number.toFixed(4)}`;
  return `$${number.toFixed(2)}`;
}
