import { buildTimelineRows } from "./data.js";
import { renderMessagePane, replacePanePart } from "./panes.js";
import { directChildren, escapeAttr, escapeHtml, formatTimelineTime, htmlToElement, insertChildAt } from "./utils.js";

export function renderLayout(els, agents, resultMaps, state, context) {
  if (state.view === "single") {
    renderSingle(els, agents, resultMaps, state, context);
  } else if (state.syncScroll && state.data.hasTimestamps) {
    renderSyncedColumns(els, agents, resultMaps, state, context);
  } else {
    renderColumns(els, agents, resultMaps, context);
  }
}

function renderColumns(els, agents, resultMaps, context) {
  ensureAppLayout(els, "columns", `<div class="columns-board"></div>`);
  const board = els.app.querySelector(".columns-board");
  board.style.setProperty("--lane-count", String(Math.max(agents.length, 1)));
  reconcileLanes(board, agents, resultMaps, context);
}

function renderSingle(els, agents, resultMaps, state, context) {
  const agent = agents.find((candidate) => candidate.id === state.selectedAgentId) || agents[0];
  if (!agent) {
    els.app.innerHTML = `<div class="empty-state">Aucun agent trouvé.</div>`;
    els.app.dataset.layoutKey = "empty";
    return;
  }
  ensureAppLayout(
    els,
    `single:${agent.id}`,
    `
    <section class="single-chat">
      ${renderLaneHeader(agent, "single-header")}
      <div class="message-list scroll-region" data-scroll-key="single:${escapeAttr(agent.id)}">
      </div>
    </section>
  `,
  );
  const section = els.app.querySelector(".single-chat");
  renderMessagePane(section, agent, resultMaps.get(agent.id), context, {
    scrollKey: `single:${agent.id}`,
    showEmpty: true,
    updateChrome: (root) => updateLaneHeader(root, agent, "single-header"),
  });
}

function renderSyncedColumns(els, agents, resultMaps, state, context) {
  ensureAppLayout(
    els,
    "timeline",
    `
    <div class="timeline-scroll scroll-region" data-scroll-key="timeline">
      <div class="timeline-grid"></div>
    </div>
  `,
  );

  const grid = els.app.querySelector(".timeline-grid");
  grid.style.setProperty("--timeline-agent-count", String(Math.max(agents.length, 1)));
  grid.style.minWidth = `${96 + Math.max(agents.length, 1) * 280}px`;
  reconcileTimelineHeaders(grid, agents);
  const rows = buildTimelineRows(agents, resultMaps, context.search || "");
  reconcileTimelineRows(grid, rows, agents, resultMaps, context);
}

function ensureAppLayout(els, layoutKey, markup) {
  if (els.app.dataset.layoutKey === layoutKey) return;
  els.app.innerHTML = markup;
  els.app.dataset.layoutKey = layoutKey;
}

function reconcileLanes(board, agents, resultMaps, context) {
  const existing = new Map(
    directChildren(board)
      .filter((child) => child.classList.contains("lane") && child.dataset.laneId)
      .map((child) => [child.dataset.laneId, child]),
  );
  const desiredIds = new Set(agents.map((agent) => agent.id));

  existing.forEach((lane, id) => {
    if (!desiredIds.has(id)) lane.remove();
  });

  agents.forEach((agent, index) => {
    let lane = existing.get(agent.id);
    if (!lane) lane = htmlToElement(renderLaneShell(agent));

    renderMessagePane(lane, agent, resultMaps.get(agent.id), context, {
      scrollKey: `lane:${agent.id}`,
      showEmpty: true,
      updateChrome: (root) => updateLaneHeader(root, agent, "lane-header"),
    });
    insertChildAt(board, lane, index);
  });
}

function renderLaneShell(agent) {
  return `
    <section class="lane" data-lane-id="${escapeAttr(agent.id)}">
      ${renderLaneHeader(agent, "lane-header")}
      <div class="message-list scroll-region" data-scroll-key="lane:${escapeAttr(agent.id)}">
      </div>
    </section>
  `;
}

function updateLaneHeader(container, agent, className) {
  replacePanePart(container, `.${className}`, renderLaneHeader(agent, className));
}

function renderLaneHeader(agent, className) {
  const stats = agent.stats || {};
  const closeButton =
    agent.kind === "disposable-run"
      ? `
        <button class="icon-button lane-close-button" type="button" data-action="close-run-column" data-run-id="${escapeAttr(agent.id)}" title="Retirer la colonne" aria-label="Retirer la colonne">
          &times;
        </button>
      `
      : "";
  return `
    <header class="${className}">
      <div class="lane-title">
        <h2>${escapeHtml(agent.name)}</h2>
        <p>${escapeHtml(agent.threadId)}${agent.exists ? "" : " · absent"}</p>
      </div>
      <div class="lane-header-side">
        <div class="stats">
          <span class="stat">${stats.messages || 0} msg</span>
          <span class="stat">${stats.toolCalls || 0} outils</span>
          <span class="stat">${stats.disposableAgentCalls || 0} agents</span>
        </div>
        ${closeButton}
      </div>
    </header>
  `;
}

function reconcileTimelineHeaders(grid, agents) {
  const headerKey = agents.map((agent) => agent.id).join("|");
  if (grid.dataset.headerKey !== headerKey) {
    directChildren(grid)
      .filter((child) => !child.classList.contains("timeline-row"))
      .forEach((child) => child.remove());
    grid.prepend(
      htmlToElement(`<div class="time-header" data-timeline-header="time"></div>`),
      ...agents.map((agent) => htmlToElement(renderTimelineAgentHeader(agent))),
    );
    grid.dataset.headerKey = headerKey;
    return;
  }

  agents.forEach((agent) => {
    const header = directChildren(grid).find((child) => child.dataset.timelineAgentId === agent.id);
    if (header) header.replaceWith(htmlToElement(renderTimelineAgentHeader(agent)));
  });
}

function renderTimelineAgentHeader(agent) {
  return `
    <div class="timeline-agent-header" data-timeline-agent-id="${escapeAttr(agent.id)}">
      <div class="lane-title">
        <h2>${escapeHtml(agent.shortName || agent.name)}</h2>
        <p>${escapeHtml(agent.threadId)}</p>
      </div>
    </div>
  `;
}

function reconcileTimelineRows(grid, rows, agents, resultMaps, context) {
  const existing = new Map(
    directChildren(grid)
      .filter((child) => child.classList.contains("timeline-row") && child.dataset.rowKey)
      .map((child) => [child.dataset.rowKey, child]),
  );
  const desiredKeys = new Set(rows.map((row) => row.key));

  existing.forEach((rowElement, key) => {
    if (!desiredKeys.has(key)) rowElement.remove();
  });

  rows.forEach((row, index) => {
    let rowElement = existing.get(row.key);
    if (!rowElement) rowElement = createTimelineRow(row);

    updateTimelineRow(rowElement, row, agents, resultMaps, context);
    insertChildAt(grid, rowElement, agents.length + 1 + index);
  });
}

function createTimelineRow(row) {
  const element = document.createElement("div");
  element.className = "timeline-row";
  element.dataset.rowKey = row.key;

  const timeCell = document.createElement("div");
  timeCell.className = "time-cell";
  element.appendChild(timeCell);
  return element;
}

function updateTimelineRow(rowElement, row, agents, resultMaps, context) {
  const timeLabel = row.epochMs ? formatTimelineTime(row.epochMs) : "sans\ndate";
  const timeCell = rowElement.querySelector(".time-cell");
  if (timeCell.textContent !== timeLabel) timeCell.textContent = timeLabel;

  const existingCells = new Map(
    directChildren(rowElement)
      .filter((child) => child.classList.contains("timeline-cell") && child.dataset.agentId)
      .map((child) => [child.dataset.agentId, child]),
  );
  const desiredIds = new Set(agents.map((agent) => agent.id));

  existingCells.forEach((cell, id) => {
    if (!desiredIds.has(id)) cell.remove();
  });

  agents.forEach((agent, index) => {
    let cell = existingCells.get(agent.id);
    if (!cell) {
      cell = document.createElement("div");
      cell.className = "timeline-cell";
      cell.dataset.agentId = agent.id;
    }

    renderMessagePane(cell, agent, resultMaps.get(agent.id), context, {
      listSelector: null,
      messages: row.byAgent.get(agent.id) || [],
      showEmpty: false,
    });
    insertChildAt(rowElement, cell, index + 1);
  });
}
