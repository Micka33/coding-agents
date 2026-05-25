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

  const pinned = options.pinned || capturePinnedScrollers();
  const firstLoad = options.firstLoad || false;

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
  els.app.innerHTML = `
    <div class="columns-board">
      ${agents.map((agent) => renderLane(agent, resultMaps.get(agent.id))).join("")}
    </div>
  `;
}

function renderSingle(agents, resultMaps) {
  const agent = agents.find((candidate) => candidate.id === state.selectedAgentId) || agents[0];
  if (!agent) {
    els.app.innerHTML = `<div class="empty-state">Aucun agent trouvé.</div>`;
    return;
  }
  els.app.innerHTML = `
    <section class="single-chat">
      ${renderLaneHeader(agent, "single-header")}
      <div class="message-list scroll-region" data-scroll-key="single:${escapeAttr(agent.id)}">
        ${renderMessageList(agent, resultMaps.get(agent.id))}
      </div>
    </section>
  `;
}

function renderLane(agent, maps) {
  return `
    <section class="lane">
      ${renderLaneHeader(agent, "lane-header")}
      <div class="message-list scroll-region" data-scroll-key="lane:${escapeAttr(agent.id)}">
        ${renderMessageList(agent, maps)}
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

function renderMessageList(agent, maps) {
  const messages = renderableMessages(agent, maps);
  if (!messages.length) {
    return `<div class="empty-state">Aucun message à afficher.</div>`;
  }
  return messages.map((message) => renderMessage(message, agent, maps)).join("");
}

function renderSyncedColumns(agents, resultMaps) {
  const rows = buildTimelineRows(agents, resultMaps);
  const header = `
    <div class="time-header"></div>
    ${agents
      .map(
        (agent) => `
          <div class="timeline-agent-header">
            <div class="lane-title">
              <h2>${escapeHtml(agent.shortName || agent.name)}</h2>
              <p>${escapeHtml(agent.threadId)}</p>
            </div>
          </div>
        `,
      )
      .join("")}
  `;

  const body = rows
    .map((row) => {
      const timeLabel = row.epochMs ? formatTimelineTime(row.epochMs) : "sans\ndate";
      const cells = agents
        .map((agent) => {
          const maps = resultMaps.get(agent.id);
          const messages = row.byAgent.get(agent.id) || [];
          return `
            <div class="timeline-cell">
              ${messages.map((message) => renderMessage(message, agent, maps)).join("")}
            </div>
          `;
        })
        .join("");
      return `<div class="time-cell">${escapeHtml(timeLabel)}</div>${cells}`;
    })
    .join("");

  els.app.innerHTML = `
    <div class="timeline-scroll scroll-region" data-scroll-key="timeline">
      <div class="timeline-grid">${header}${body}</div>
    </div>
  `;
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

function renderMessage(message, agent, maps) {
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

  const blocks = message.blocks.map((block) => renderBlock(block)).join("");
  const calls = message.toolCalls
    .map((call) => renderToolCall(call, maps?.byToolCallId.get(call.id)))
    .join("");
  const fallback = !blocks && !calls && message.contentText
    ? `<div class="text-block">${escapeHtml(message.contentText)}</div>`
    : "";

  return `
    <article class="${messageClass}" data-message-id="${escapeAttr(message.id)}" data-ts="${message.timestamp?.epochMs || ""}">
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

function renderBlock(block) {
  if (block.type === "reasoning") {
    const text = block.summary || block.text;
    if (!text) return "";
    return `
      <details class="thinking">
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

function renderToolCall(call, result) {
  if (call.kind === "resident-agent") {
    const target = call.targetAgent || call.name;
    return `
      <details class="tool-call resident-agent">
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
      <details class="tool-call disposable-agent">
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
    <details class="tool-call generic-tool">
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

function capturePinnedScrollers() {
  const pinned = new Map();
  document.querySelectorAll(".scroll-region").forEach((element) => {
    const key = element.dataset.scrollKey;
    if (!key) return;
    pinned.set(key, isNearBottom(element));
  });
  return pinned;
}

function restorePinnedScrollers(pinned, firstLoad = false) {
  const apply = () => {
    document.querySelectorAll(".scroll-region").forEach((element) => {
      const key = element.dataset.scrollKey;
      const shouldPin = firstLoad || pinned.get(key) !== false;
      if (shouldPin) scrollRegionToBottom(element);
    });
  };
  requestAnimationFrame(() => {
    apply();
    setTimeout(apply, 50);
    setTimeout(apply, 250);
  });
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
