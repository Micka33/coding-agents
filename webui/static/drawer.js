import { buildResultMaps, runAsAgent } from "./data.js";
import { reconcileMessageList } from "./messageList.js";
import { escapeAttr, escapeHtml } from "./utils.js";

export function renderRunDrawer(els, state, context) {
  if (!state.drawerRunId) {
    els.drawerRoot.innerHTML = "";
    document.body.classList.remove("drawer-open");
    return;
  }

  document.body.classList.add("drawer-open");
  const run = state.taskRunCache.get(state.drawerRunId);
  const summary = context.taskRunById.get(state.drawerRunId);
  const displayRun = run || summary;

  els.drawerRoot.innerHTML = renderDrawerShell(displayRun, state);

  if (!run?.messages) return;

  const agent = runAsAgent(run);
  const resultMaps = buildResultMaps([agent]);
  const list = els.drawerRoot.querySelector(".drawer-message-list");
  if (list) {
    reconcileMessageList(list, agent, resultMaps.get(agent.id), context, { showEmpty: true });
  }
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
      <header class="drawer-header">
        <div class="lane-title">
          <h2>${escapeHtml(title)}</h2>
          <p>${escapeHtml(run?.checkpointNs || state.drawerRunId)}</p>
        </div>
        <button class="icon-button" type="button" data-action="close-run-drawer" title="Fermer" aria-label="Fermer">&times;</button>
      </header>
      <div class="drawer-toolbar">
        <button class="mini-button" type="button" data-action="${columnAction}" data-run-id="${escapeAttr(state.drawerRunId)}">
          ${isColumnOpen ? "Retirer la colonne" : "Ouvrir en colonne"}
        </button>
        <span class="run-metrics">${escapeHtml((stats.messages || 0) + " msg · " + (stats.toolCalls || 0) + " outils")}</span>
      </div>
      <div class="drawer-body">
        ${body}
      </div>
    </aside>
  `;
}
