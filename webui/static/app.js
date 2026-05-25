const state = {
  data: null,
  selectedThreadId: null,
  selectedAgentId: "manager",
  view: "columns",
  syncScroll: false,
  live: true,
  search: "",
  loading: false,
  pollTimer: null,
  openDetails: new Map(),
};

const els = {
  app: document.querySelector("#app"),
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

init();

function init() {
  els.app.addEventListener("toggle", handleDetailsToggle, true);

  els.viewButtons.forEach((button) => {
    button.addEventListener("click", () => {
      state.view = button.dataset.view;
      render();
    });
  });

  els.threadSelect.addEventListener("change", () => {
    state.selectedThreadId = els.threadSelect.value;
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

  els.searchInput.addEventListener("input", () => {
    state.search = els.searchInput.value.trim().toLowerCase();
    render({ preserveScroll: false });
  });

  els.refreshButton.addEventListener("click", () => loadState());
  loadState({ preserveScroll: false });
  schedulePolling();
}

function schedulePolling() {
  if (state.pollTimer) {
    clearInterval(state.pollTimer);
    state.pollTimer = null;
  }
  if (!state.live) {
    setStatus("Live en pause");
    return;
  }
  state.pollTimer = setInterval(() => loadState(), 1800);
}

async function loadState(options = {}) {
  if (state.loading) return;
  state.loading = true;

  const preserveScroll = options.preserveScroll !== false;
  const pinned = preserveScroll ? capturePinnedScrollers() : new Map();
  const firstLoad = state.data === null || !preserveScroll;

  try {
    const params = new URLSearchParams();
    if (state.selectedThreadId) params.set("thread_id", state.selectedThreadId);
    const response = await fetch(`/api/state?${params.toString()}`, { cache: "no-store" });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "Erreur API");

    state.data = payload;
    state.selectedThreadId = payload.activeThreadId;
    if (!payload.agents.some((agent) => agent.id === state.selectedAgentId)) {
      state.selectedAgentId = payload.agents[0]?.id || "manager";
    }
    renderControls();
    render({ pinned, firstLoad });
    const generated = payload.generatedAt?.epochMs
      ? formatTime(payload.generatedAt.epochMs)
      : "maintenant";
    setStatus(`À jour: ${generated}`);
  } catch (error) {
    setStatus(error.message, true);
  } finally {
    state.loading = false;
  }
}

function render(options = {}) {
  if (!state.data) return;

  const preserveScroll = options.preserveScroll !== false;
  const pinned = preserveScroll ? options.pinned || capturePinnedScrollers() : new Map();
  const firstLoad = options.firstLoad || !preserveScroll;

  renderControls();
  const agents = state.data.agents;
  const resultMaps = buildResultMaps(agents);

  if (state.view === "single") {
    renderSingle(agents, resultMaps);
  } else if (state.syncScroll && state.data.hasTimestamps) {
    renderSyncedColumns(agents, resultMaps);
  } else {
    renderColumns(agents, resultMaps);
  }

  restorePinnedScrollers(pinned, firstLoad);
}

function handleDetailsToggle(event) {
  const details = event.target;
  if (!(details instanceof HTMLDetailsElement)) return;
  const key = details.dataset.detailKey;
  if (key) state.openDetails.set(key, details.open);
}

function renderControls() {
  els.dbPath.textContent = state.data?.dbPath || "";

  const currentThreadOptions = state.data?.threads || [];
  els.threadSelect.innerHTML = currentThreadOptions
    .map((thread) => {
      const updated = thread.updatedAt?.epochMs ? formatTime(thread.updatedAt.epochMs) : "sans date";
      return `<option value="${escapeAttr(thread.id)}">${escapeHtml(thread.id)} · ${escapeHtml(updated)}</option>`;
    })
    .join("");
  if (state.selectedThreadId) els.threadSelect.value = state.selectedThreadId;

  els.agentSelect.innerHTML = (state.data?.agents || [])
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

function renderColumns(agents, resultMaps) {
  ensureAppLayout("columns", `<div class="columns-board"></div>`);
  const board = els.app.querySelector(".columns-board");
  reconcileLanes(board, agents, resultMaps);
}

function renderSingle(agents, resultMaps) {
  const agent = agents.find((candidate) => candidate.id === state.selectedAgentId) || agents[0];
  if (!agent) {
    els.app.innerHTML = `<div class="empty-state">Aucun agent trouvé.</div>`;
    els.app.dataset.layoutKey = "empty";
    return;
  }
  ensureAppLayout(
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
  updateLaneHeader(section, agent, "single-header");
  reconcileMessageList(section.querySelector(".message-list"), agent, resultMaps.get(agent.id), {
    showEmpty: true,
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

function renderLaneHeader(agent, className) {
  const stats = agent.stats || {};
  return `
    <header class="${className}">
      <div class="lane-title">
        <h2>${escapeHtml(agent.name)}</h2>
        <p>${escapeHtml(agent.threadId)}${agent.exists ? "" : " · absent"}</p>
      </div>
      <div class="stats">
        <span class="stat">${stats.messages || 0} msg</span>
        <span class="stat">${stats.toolCalls || 0} outils</span>
        <span class="stat">${stats.disposableAgentCalls || 0} agents</span>
      </div>
    </header>
  `;
}

function renderSyncedColumns(agents, resultMaps) {
  ensureAppLayout(
    "timeline",
    `
    <div class="timeline-scroll scroll-region" data-scroll-key="timeline">
      <div class="timeline-grid"></div>
    </div>
  `,
  );

  const grid = els.app.querySelector(".timeline-grid");
  reconcileTimelineHeaders(grid, agents);
  const rows = buildTimelineRows(agents, resultMaps);
  reconcileTimelineRows(grid, rows, agents, resultMaps);
}

function ensureAppLayout(layoutKey, markup) {
  if (els.app.dataset.layoutKey === layoutKey) return;
  els.app.innerHTML = markup;
  els.app.dataset.layoutKey = layoutKey;
}

function reconcileLanes(board, agents, resultMaps) {
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

    updateLaneHeader(lane, agent, "lane-header");
    const list = lane.querySelector(".message-list");
    list.dataset.scrollKey = `lane:${agent.id}`;
    reconcileMessageList(list, agent, resultMaps.get(agent.id), { showEmpty: true });
    insertChildAt(board, lane, index);
  });
}

function updateLaneHeader(container, agent, className) {
  const current = container.querySelector(`.${className}`);
  const next = htmlToElement(renderLaneHeader(agent, className));
  if (current) current.replaceWith(next);
  else container.prepend(next);
}

function reconcileMessageList(container, agent, maps, options = {}) {
  const messages = "messages" in options ? options.messages : renderableMessages(agent, maps);
  const showEmpty = options.showEmpty !== false;
  const existing = new Map(
    directChildren(container)
      .filter((child) => child.classList.contains("message") && child.dataset.messageKey)
      .map((child) => [child.dataset.messageKey, child]),
  );
  const desiredKeys = new Set(messages.map((message) => messageKey(agent, message)));

  directChildren(container)
    .filter((child) => child.classList.contains("empty-state"))
    .forEach((child) => child.remove());

  existing.forEach((element, key) => {
    if (!desiredKeys.has(key)) element.remove();
  });

  if (!messages.length) {
    if (showEmpty) {
      container.appendChild(htmlToElement(`<div class="empty-state">Aucun message à afficher.</div>`));
    }
    return;
  }

  messages.forEach((message) => {
    const key = messageKey(agent, message);
    const signature = messageSignature(message, maps);
    let element = existing.get(key);

    if (!element) {
      element = createMessageElement(message, agent, maps);
    } else if (element.dataset.renderHash !== signature) {
      const openDetails = captureDetailsState(element);
      rememberDetailsState(openDetails);
      const replacement = createMessageElement(message, agent, maps, openDetails);
      element.replaceWith(replacement);
      element = replacement;
    }

    container.appendChild(element);
  });
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

function reconcileTimelineRows(grid, rows, agents, resultMaps) {
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

    updateTimelineRow(rowElement, row, agents, resultMaps);
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

function updateTimelineRow(rowElement, row, agents, resultMaps) {
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

    const maps = resultMaps.get(agent.id);
    reconcileMessageList(cell, agent, maps, {
      messages: row.byAgent.get(agent.id) || [],
      showEmpty: false,
    });
    insertChildAt(rowElement, cell, index + 1);
  });
}

function buildTimelineRows(agents, resultMaps) {
  const rows = new Map();
  let noTimestampOrder = 0;

  agents.forEach((agent) => {
    const maps = resultMaps.get(agent.id);
    renderableMessages(agent, maps).forEach((message) => {
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

function buildResultMaps(agents) {
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

function renderableMessages(agent, maps) {
  return agent.messages.filter((message) => {
    if (maps?.pairedToolResultIds.has(message.id)) return false;
    if (!state.search) return true;
    return searchableText(message, maps).toLowerCase().includes(state.search);
  });
}

function createMessageElement(message, agent, maps, openDetails = new Map()) {
  const element = htmlToElement(renderMessage(message, agent, maps));
  restoreDetailsState(element, openDetails);
  return element;
}

function messageKey(agent, message) {
  const scope = `${agent.id}:${agent.threadId || ""}`;
  if (message.id) return `${scope}:${message.id}`;
  return `${scope}:fallback:${hashString(
    JSON.stringify([
      message.timestamp?.epochMs || "",
      message.type || "",
      message.name || "",
      message.rawType || "",
      message.contentText || "",
      (message.toolCalls || []).map((call) => call.id || call.name || ""),
    ]),
  )}`;
}

function messageSignature(message, maps) {
  const relatedResults = (message.toolCalls || []).map((call) => {
    const result = maps?.byToolCallId.get(call.id);
    return {
      callId: call.id,
      resultId: result?.id,
      resultText: result?.contentText,
      resultTimestamp: result?.timestamp?.epochMs,
    };
  });
  return hashString(JSON.stringify({ message, relatedResults }));
}

function renderMessage(message, agent, maps) {
  const key = messageKey(agent, message);
  const signature = messageSignature(message, maps);
  const speaker = speakerLabel(message, agent);
  const time = message.timestamp?.epochMs ? formatTime(message.timestamp.epochMs) : "";
  const accent = agent.accent || agent.id;
  const messageClass = [
    "message",
    accent,
    message.type === "human" ? "human" : "",
    message.type === "tool" ? "tool" : "",
  ]
    .filter(Boolean)
    .join(" ");

  const blocks = message.blocks.map((block, index) => renderBlock(block, message, agent, index)).join("");
  const calls = message.toolCalls
    .map((call, index) => renderToolCall(call, maps?.byToolCallId.get(call.id), message, agent, index))
    .join("");
  const fallback = !blocks && !calls && message.contentText
    ? `<div class="text-block">${escapeHtml(message.contentText)}</div>`
    : "";

  return `
    <article class="${messageClass}" data-message-id="${escapeAttr(message.id)}" data-message-key="${escapeAttr(key)}" data-render-hash="${escapeAttr(signature)}" data-ts="${message.timestamp?.epochMs || ""}">
      <div class="message-header">
        <div class="speaker">${escapeHtml(speaker)}</div>
        <time class="timestamp">${escapeHtml(time)}</time>
      </div>
      ${blocks}
      ${calls}
      ${fallback}
    </article>
  `;
}

function captureDetailsState(root) {
  const detailsState = new Map();
  root.querySelectorAll("details[data-detail-key]").forEach((details) => {
    detailsState.set(details.dataset.detailKey, details.open);
  });
  return detailsState;
}

function rememberDetailsState(detailsState) {
  detailsState.forEach((open, key) => state.openDetails.set(key, open));
}

function restoreDetailsState(root, overrides = new Map()) {
  root.querySelectorAll("details[data-detail-key]").forEach((details) => {
    const key = details.dataset.detailKey;
    if (overrides.has(key)) {
      details.open = overrides.get(key);
    } else if (state.openDetails.has(key)) {
      details.open = state.openDetails.get(key);
    }
  });
}

function renderBlock(block, message, agent, index) {
  if (block.type === "reasoning") {
    const text = block.summary || block.text;
    if (!text) return "";
    const detailKey = `${messageKey(agent, message)}:reasoning:${index}`;
    return `
      <details class="thinking" data-detail-key="${escapeAttr(detailKey)}">
        <summary><span>Réflexion</span><span class="badge">collapsed</span></summary>
        <div class="thinking-body">
          <div class="text-block">${escapeHtml(text)}</div>
        </div>
      </details>
    `;
  }

  if (!block.text) return "";
  const phase = block.phase ? `<span class="badge">${escapeHtml(block.phase)}</span>` : "";
  return `
    <div class="text-block">${phase}${phase ? "\n" : ""}${escapeHtml(block.text)}</div>
  `;
}

function renderToolCall(call, result, message, agent, index) {
  const detailKey = `${messageKey(agent, message)}:tool:${call.id || `${index}:${call.name}`}`;

  if (call.kind === "resident-agent") {
    const target = call.targetAgent || call.name;
    return `
      <details class="tool-call resident-agent" data-detail-key="${escapeAttr(detailKey)}">
        <summary>
          <span class="call-heading">
            <span class="call-name">Consultation ${escapeHtml(displayAgentName(target))}</span>
            <span class="badge resident">agent persistant</span>
          </span>
        </summary>
        <div class="tool-body">
          <div class="text-block">Input et résultat masqués dans cette colonne.</div>
        </div>
      </details>
    `;
  }

  if (call.kind === "disposable-agent") {
    const target = call.targetAgent || "agent";
    const description = call.args?.description || prettyJson(call.args);
    const resultText = result?.contentText || "Résultat pas encore disponible.";
    return `
      <details class="tool-call disposable-agent" data-detail-key="${escapeAttr(detailKey)}">
        <summary>
          <span class="call-heading">
            <span class="call-name">Appel ${escapeHtml(target)}</span>
            <span class="badge disposable">agent non persistant</span>
          </span>
        </summary>
        <div class="tool-body">
          <section class="tool-section">
            <h3>Input</h3>
            <pre class="tool-pre">${escapeHtml(description)}</pre>
          </section>
          <section class="tool-section">
            <h3>Résultat</h3>
            <pre class="tool-pre">${escapeHtml(resultText)}</pre>
          </section>
        </div>
      </details>
    `;
  }

  const resultText = result?.contentText || "Résultat pas encore disponible.";
  return `
    <details class="tool-call generic-tool" data-detail-key="${escapeAttr(detailKey)}">
      <summary>
        <span class="call-heading">
          <span class="call-name">${escapeHtml(call.name)}</span>
          <span class="badge">outil</span>
        </span>
      </summary>
      <div class="tool-body">
        <section class="tool-section">
          <h3>Input</h3>
          <pre class="tool-pre">${escapeHtml(prettyJson(call.args || call.rawArguments || {}))}</pre>
        </section>
        <section class="tool-section">
          <h3>Résultat</h3>
          <pre class="tool-pre">${escapeHtml(resultText)}</pre>
        </section>
      </div>
    </details>
  `;
}

function speakerLabel(message, agent) {
  if (message.type === "human") {
    return agent.id === "manager" ? "Humain" : "Manager";
  }
  if (message.type === "ai") return agent.name;
  if (message.type === "tool") return `Outil: ${message.name || "résultat"}`;
  return message.name || message.rawType || "Message";
}

function displayAgentName(agentId) {
  const known = {
    manager: "manager",
    "product-analyst": "product analyst",
    "software-architect": "software architect",
  };
  return known[agentId] || agentId;
}

function searchableText(message, maps) {
  const parts = [message.contentText, message.name, message.rawType];
  message.blocks.forEach((block) => parts.push(block.text, block.summary, block.phase));
  message.toolCalls.forEach((call) => {
    parts.push(call.name, call.kind, call.targetAgent, prettyJson(call.args));
    const result = maps?.byToolCallId.get(call.id);
    if (result) parts.push(result.contentText);
  });
  return parts.filter(Boolean).join("\n");
}

function prettyJson(value) {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function directChildren(element) {
  return Array.from(element?.children || []);
}

function insertChildAt(parent, child, index) {
  const current = parent.children[index] || null;
  if (current !== child) parent.insertBefore(child, current);
}

function htmlToElement(markup) {
  const template = document.createElement("template");
  template.innerHTML = markup.trim();
  return template.content.firstElementChild;
}

function hashString(value) {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(36);
}

function capturePinnedScrollers() {
  const pinned = new Map();
  document.querySelectorAll(".scroll-region").forEach((element) => {
    const key = element.dataset.scrollKey;
    if (!key) return;
    pinned.set(key, {
      nearBottom: isNearBottom(element),
      scrollTop: element.scrollTop,
    });
  });
  return pinned;
}

function restorePinnedScrollers(pinned, firstLoad = false) {
  const apply = () => {
    document.querySelectorAll(".scroll-region").forEach((element) => {
      const key = element.dataset.scrollKey;
      const previous = pinned.get(key);
      const shouldPin = firstLoad || !previous || previous.nearBottom;
      if (shouldPin) {
        scrollRegionToBottom(element);
      } else {
        restoreScrollRegion(element, previous);
      }
    });
  };
  requestAnimationFrame(() => {
    apply();
    setTimeout(apply, 50);
    setTimeout(apply, 250);
  });
}

function restoreScrollRegion(element, previous) {
  const maxScrollTop = Math.max(0, element.scrollHeight - element.clientHeight);
  element.scrollTop = Math.min(previous.scrollTop, maxScrollTop);
}

function scrollRegionToBottom(element) {
  element.scrollTop = Math.max(0, element.scrollHeight - element.clientHeight);
  const lastChild = element.lastElementChild;
  if (lastChild && typeof lastChild.scrollIntoView === "function") {
    lastChild.scrollIntoView({ block: "end", inline: "nearest" });
  }
}

function isNearBottom(element) {
  return element.scrollHeight - element.clientHeight - element.scrollTop < 90;
}

function setStatus(text, isError = false) {
  els.status.textContent = text || "";
  els.status.classList.toggle("error", isError);
}

function formatTime(epochMs) {
  return new Intl.DateTimeFormat(undefined, {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(epochMs));
}

function formatTimelineTime(epochMs) {
  return new Intl.DateTimeFormat(undefined, {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  })
    .format(new Date(epochMs))
    .replace(", ", "\n");
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function escapeAttr(value) {
  return escapeHtml(value).replaceAll("`", "&#096;");
}
