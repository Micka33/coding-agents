import { buildResultMaps, columnOptions, runAsAgent } from "./data.js";
import { clearMessagePaneHost, renderMessagePane, replacePanePart } from "./panes.js";
import { escapeAttr, escapeHtml, formatCompactNumber, formatCost, hashString, htmlToElement } from "./utils.js";

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
  const target = resolveCostTarget(state, agents);
  const shellKey = costDrawerKey(state);

  if (root.dataset.messagePaneKey !== shellKey || root.dataset.messagePaneMode !== "cost") {
    root.innerHTML = renderCostDrawerShell(target, state, shellKey);
    root.dataset.messagePaneKey = shellKey;
    root.dataset.messagePaneMode = "cost";
    return;
  }

  updateCostDrawer(root, target, state, shellKey);
  root.dataset.messagePaneKey = shellKey;
  root.dataset.messagePaneMode = "cost";
}

function renderCostDrawerShell(target, state, shellKey) {
  const cost = target.cost || {};
  return `
    <div class="drawer-backdrop" data-action="close-cost-breakdown"></div>
    <aside class="run-drawer cost-drawer" role="dialog" aria-label="${escapeAttr(target.title)}">
      ${renderCostDrawerHeader(target)}
      ${renderCostDrawerToolbar(cost, state)}
      ${renderCostDrawerBodyShell(target, cost, state, shellKey)}
    </aside>
  `;
}

function updateCostDrawer(root, target, state, shellKey) {
  const drawer = root.querySelector(".cost-drawer");
  if (!drawer) {
    root.innerHTML = renderCostDrawerShell(target, state, shellKey);
    return;
  }

  const cost = target.cost || {};
  drawer.setAttribute("aria-label", target.title);
  replacePanePart(drawer, ".drawer-header", renderCostDrawerHeader(target));
  replacePanePart(drawer, ".drawer-toolbar", renderCostDrawerToolbar(cost, state));
  updateCostDrawerBody(drawer, target, cost, state, shellKey);
}

function renderCostDrawerHeader(target) {
  return `
    <header class="drawer-header">
      <div class="lane-title">
        <h2>${escapeHtml(target.title)}</h2>
        <p>${escapeHtml(target.subtitle)}</p>
      </div>
      <button class="icon-button" type="button" data-action="close-cost-breakdown" title="Fermer" aria-label="Fermer">&times;</button>
    </header>
  `;
}

function renderCostDrawerToolbar(cost, state) {
  return `
    <div class="drawer-toolbar">
      <span class="cost-total">${escapeHtml(formatCost(cost))}</span>
      <span class="run-metrics">${escapeHtml(cost.tier || state.data?.pricing?.tier || "standard")} · ${escapeHtml(cost.currency || "USD")}</span>
      ${cost.partial ? `<span class="badge cost-warning">partiel</span>` : ""}
    </div>
  `;
}

function renderCostDrawerBodyShell(target, cost, state, shellKey) {
  const body = renderCostDrawerBody(target, cost, state);
  return `
    <div
      class="drawer-body cost-drawer-body scroll-region"
      data-scroll-key="${escapeAttr(shellKey)}"
      data-render-hash="${escapeAttr(hashString(body))}"
    >
      ${body}
    </div>
  `;
}

function updateCostDrawerBody(drawer, target, cost, state, shellKey) {
  const body = drawer.querySelector(".cost-drawer-body");
  if (!body) {
    drawer.appendChild(htmlToElement(renderCostDrawerBodyShell(target, cost, state, shellKey)));
    return;
  }

  body.classList.add("scroll-region");
  body.dataset.scrollKey = shellKey;
  const nextBody = renderCostDrawerBody(target, cost, state);
  const nextHash = hashString(nextBody);
  if (body.dataset.renderHash !== nextHash) {
    body.innerHTML = nextBody;
    body.dataset.renderHash = nextHash;
  }
}

function renderCostDrawerBody(target, cost, state) {
  return `
    ${renderCostSummary(cost, state)}
    ${renderCostChart(cost, state)}
    ${renderCostParts(cost)}
    ${renderCostSources(target.sources)}
    ${renderModelBreakdown(cost)}
    ${renderUnpricedModels(cost)}
  `;
}

function costDrawerKey(state) {
  const breakdown = state.costBreakdown || { scope: "thread", id: "" };
  return `cost:${breakdown.scope || "thread"}:${breakdown.id || ""}`;
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

function renderCostChart(cost, state) {
  const granularity = normalizeGranularity(state.costChartGranularity);
  const buckets = cost.time_series?.[granularity] || [];
  const maxCost = Math.max(...buckets.map((bucket) => Number(bucket.estimated_cost_usd || 0)), 0);
  const totalCalls = buckets.reduce((sum, bucket) => sum + (bucket.calls || 0), 0);
  const peak = buckets.reduce((best, bucket) => {
    return Number(bucket.estimated_cost_usd || 0) > Number(best?.estimated_cost_usd || 0) ? bucket : best;
  }, null);
  const innerWidth = Math.max(100, buckets.length * 28);

  return `
    <section class="cost-section cost-chart-section">
      <div class="cost-section-header">
        <h3>Coût dans le temps</h3>
        <div class="cost-chart-tabs" role="group" aria-label="Granularité coût">
          ${renderGranularityButton("hour", "Heure", granularity)}
          ${renderGranularityButton("day", "Jour", granularity)}
          ${renderGranularityButton("week", "Semaine", granularity)}
        </div>
      </div>
      <div class="cost-chart-meta">
        <span>${escapeHtml(`${buckets.length} bucket${buckets.length > 1 ? "s" : ""}`)}</span>
        <span>${escapeHtml(`${totalCalls} appels`)}</span>
        ${peak ? `<span>Pic ${escapeHtml(formatUsd(peak.estimated_cost_usd_decimal))} · ${escapeHtml(peak.label || peak.bucket)}</span>` : ""}
        ${cost.unbucketed_calls ? `<span>${escapeHtml(String(cost.unbucketed_calls))} sans timestamp</span>` : ""}
      </div>
      ${buckets.length ? `
        <div class="cost-chart-scroll" tabindex="0" aria-label="Bar chart coût par ${escapeAttr(granularityLabel(granularity).toLowerCase())}">
          <div class="cost-chart-bars" style="width: max(100%, ${innerWidth}px);">
            ${buckets.map((bucket) => renderCostBar(bucket, maxCost)).join("")}
          </div>
        </div>
      ` : `<div class="empty-state compact-empty">Aucun timestamp exploitable pour ce coût.</div>`}
    </section>
  `;
}

function renderGranularityButton(value, label, active) {
  return `
    <button
      class="${value === active ? "active" : ""}"
      type="button"
      data-action="set-cost-granularity"
      data-granularity="${escapeAttr(value)}"
      aria-pressed="${value === active ? "true" : "false"}"
    >
      ${escapeHtml(label)}
    </button>
  `;
}

function renderCostBar(bucket, maxCost) {
  const cost = Number(bucket.estimated_cost_usd || 0);
  const height = maxCost > 0 ? Math.max(4, Math.round((cost / maxCost) * 100)) : 0;
  const title = `${bucket.label || bucket.bucket}: ${formatUsd(bucket.estimated_cost_usd_decimal)} · ${bucket.calls || 0} appels`;
  return `
    <div class="cost-bar-item" title="${escapeAttr(title)}">
      <div class="cost-bar-track">
        <div class="cost-bar-fill" style="height: ${height}%;"></div>
      </div>
      <span>${escapeHtml(shortBucketLabel(bucket.label || bucket.bucket))}</span>
    </div>
  `;
}

function normalizeGranularity(value) {
  return ["hour", "day", "week"].includes(value) ? value : "day";
}

function granularityLabel(value) {
  return { hour: "Heure", day: "Jour", week: "Semaine" }[normalizeGranularity(value)];
}

function shortBucketLabel(value) {
  return String(value || "").replace(/^\d{4}\s+/, "");
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
