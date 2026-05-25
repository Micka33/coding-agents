import { buildResultMaps, runAsAgent } from "./data.js";
import { clearMessagePaneHost, renderMessagePane, replacePanePart } from "./panes.js";
import { escapeAttr, escapeHtml } from "./utils.js";

export function renderRunDrawer(els, state, context) {
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
      <span class="run-metrics">${escapeHtml((stats.messages || 0) + " msg · " + (stats.toolCalls || 0) + " outils")}</span>
    </div>
  `;
}
