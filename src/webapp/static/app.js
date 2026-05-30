const els = {
  roomMeta: document.querySelector("#roomMeta"),
  messages: document.querySelector("#messages"),
  hookToggle: document.querySelector("#hookToggle"),
  cascadeLimit: document.querySelector("#cascadeLimit"),
  composer: document.querySelector("#composer"),
  messageInput: document.querySelector("#messageInput"),
  mentionSuggestions: document.querySelector("#mentionSuggestions"),
  fileInput: document.querySelector("#fileInput"),
  activityHint: document.querySelector("#activityHint"),
  activityPanel: document.querySelector("#activityPanel"),
};

let currentState = null;
let mentionMenu = {
  token: null,
  options: [],
  selectedIndex: 0,
};

async function fetchJson(url, options = {}) {
  const response = await fetch(url, { cache: "no-store", ...options });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json();
}

async function loadState() {
  currentState = await fetchJson("/api/state");
  render();
}

function render() {
  if (!currentState) return;
  els.roomMeta.textContent = `${currentState.team_id} / ${currentState.conversation_id}`;
  els.hookToggle.checked = Boolean(currentState.runtime.mention_hook_enabled);
  els.cascadeLimit.value = currentState.runtime.max_cascade_turns ?? "";
  els.messages.innerHTML = currentState.events.map(renderEvent).join("");
  const active = currentState.activity;
  if (active) {
    els.activityHint.textContent = `${active.agent_id} is replying...`;
    els.activityHint.classList.remove("hidden");
  } else {
    els.activityHint.classList.add("hidden");
  }
  if (!els.activityPanel.classList.contains("hidden")) {
    renderActivityPanel(active?.agent_id);
  }
  updateMentionSuggestions();
}

function renderEvent(event) {
  const mentions = event.mentions.length ? `<span class="mentions">${event.mentions.map(escapeHtml).join(", ")}</span>` : "";
  const files = event.attachments.length
    ? `<ul class="files">${event.attachments.map((file) => `<li>${escapeHtml(file.filename)}</li>`).join("")}</ul>`
    : "";
  return `
    <article class="message ${event.author_kind}">
      <div class="messageMeta">
        <strong>${escapeHtml(event.author_id)}</strong>
        <span>#${event.seq}</span>
        ${mentions}
      </div>
      <p>${escapeHtml(event.content)}</p>
      ${files}
    </article>
  `;
}

async function sendMessage(event) {
  event.preventDefault();
  const content = els.messageInput.value;
  const attachments = await selectedAttachments();
  await fetchJson("/api/messages", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content, attachments, wait: false }),
  });
  els.messageInput.value = "";
  els.fileInput.value = "";
  hideMentionSuggestions();
  await loadState();
}

async function selectedAttachments() {
  const files = Array.from(els.fileInput.files || []);
  return Promise.all(
    files.map(async (file) => ({
      filename: file.name,
      media_type: file.type || null,
      content_base64: await fileToBase64(file),
    })),
  );
}

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1] || "");
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

async function updateRuntime() {
  await fetchJson("/api/runtime", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      mention_hook_enabled: els.hookToggle.checked,
      max_cascade_turns: els.cascadeLimit.value ? Number(els.cascadeLimit.value) : null,
    }),
  });
  await loadState();
}

async function renderActivityPanel(agentId) {
  const state = agentId ? await fetchJson(`/api/activity?agent_id=${encodeURIComponent(agentId)}`) : currentState;
  els.activityPanel.innerHTML = `
    <header>
      <h2>${agentId ? escapeHtml(agentId) : "Activity"}</h2>
      <div class="panelActions">
        ${agentId ? '<button id="stopAgent" type="button">Stop</button>' : ""}
        <button id="closePanel" type="button">Close</button>
      </div>
    </header>
    <pre>${escapeHtml(JSON.stringify({
      private_thread_id: state.private_thread_id,
      agent_states: state.agent_states,
      deliveries: state.deliveries,
      private_messages: state.private_messages || [],
    }, null, 2))}</pre>
  `;
  els.activityPanel.querySelector("#closePanel").addEventListener("click", () => {
    els.activityPanel.classList.add("hidden");
  });
  const stopButton = els.activityPanel.querySelector("#stopAgent");
  if (stopButton && agentId) {
    stopButton.addEventListener("click", async () => {
      await fetchJson("/api/stop", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ agent_id: agentId }),
      });
      await loadState();
    });
  }
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[char]);
}

function participantOptions() {
  return [...new Set(currentState?.participants || [])]
    .filter(Boolean)
    .sort((left, right) => left.localeCompare(right));
}

function activeMentionToken() {
  const input = els.messageInput;
  const caret = input.selectionStart;
  if (caret !== input.selectionEnd) return null;

  const beforeCaret = input.value.slice(0, caret);
  const triggerIndex = beforeCaret.lastIndexOf("@");
  if (triggerIndex < 0) return null;

  const previous = triggerIndex > 0 ? beforeCaret[triggerIndex - 1] : "";
  if (previous && /[\w.]/.test(previous)) return null;

  const query = beforeCaret.slice(triggerIndex + 1);
  if (/[^A-Za-z0-9_-]/.test(query)) return null;

  return { start: triggerIndex, end: caret, query };
}

function updateMentionSuggestions() {
  const token = activeMentionToken();
  const participants = participantOptions();
  if (!token || !participants.length) {
    hideMentionSuggestions();
    return;
  }

  const query = token.query.toLowerCase();
  const options = participants.filter((participant) => participant.toLowerCase().startsWith(query));
  if (!options.length) {
    hideMentionSuggestions();
    return;
  }

  const sameQuery = mentionMenu.token?.start === token.start && mentionMenu.token.query === token.query;
  mentionMenu = {
    token,
    options,
    selectedIndex: sameQuery ? Math.min(mentionMenu.selectedIndex, options.length - 1) : 0,
  };
  renderMentionSuggestions();
}

function renderMentionSuggestions() {
  const options = mentionMenu.options;
  els.mentionSuggestions.innerHTML = options.map((participant, index) => `
    <button
      id="mention-option-${index}"
      class="${index === mentionMenu.selectedIndex ? "active" : ""}"
      type="button"
      role="option"
      aria-selected="${index === mentionMenu.selectedIndex ? "true" : "false"}"
      data-index="${index}"
    >@${escapeHtml(participant)}</button>
  `).join("");
  els.mentionSuggestions.classList.remove("hidden");
  els.messageInput.setAttribute("aria-expanded", "true");
  els.messageInput.setAttribute("aria-activedescendant", `mention-option-${mentionMenu.selectedIndex}`);
}

function hideMentionSuggestions() {
  mentionMenu = { token: null, options: [], selectedIndex: 0 };
  els.mentionSuggestions.innerHTML = "";
  els.mentionSuggestions.classList.add("hidden");
  els.messageInput.setAttribute("aria-expanded", "false");
  els.messageInput.removeAttribute("aria-activedescendant");
}

function moveMentionSelection(delta) {
  if (!mentionMenu.options.length) return;
  const nextIndex = mentionMenu.selectedIndex + delta + mentionMenu.options.length;
  mentionMenu.selectedIndex = nextIndex % mentionMenu.options.length;
  renderMentionSuggestions();
}

function completeMention(index = mentionMenu.selectedIndex) {
  const token = mentionMenu.token || activeMentionToken();
  const participant = mentionMenu.options[index];
  if (!token || !participant) return;

  const input = els.messageInput;
  const suffix = needsTrailingSpace(input.value, token.end) ? " " : "";
  const replacement = `@${participant}${suffix}`;
  input.value = `${input.value.slice(0, token.start)}${replacement}${input.value.slice(token.end)}`;
  const caret = token.start + replacement.length;
  input.setSelectionRange(caret, caret);
  input.focus();
  hideMentionSuggestions();
}

function needsTrailingSpace(value, index) {
  const next = value[index];
  return !next || !/\s/.test(next);
}

function handleMentionKeydown(event) {
  if (els.mentionSuggestions.classList.contains("hidden")) return;

  if (event.key === "ArrowDown") {
    event.preventDefault();
    moveMentionSelection(1);
  } else if (event.key === "ArrowUp") {
    event.preventDefault();
    moveMentionSelection(-1);
  } else if (event.key === "Enter" || event.key === "Tab") {
    event.preventDefault();
    completeMention();
  } else if (event.key === "Escape") {
    event.preventDefault();
    hideMentionSuggestions();
  }
}

els.composer.addEventListener("submit", sendMessage);
els.hookToggle.addEventListener("change", updateRuntime);
els.cascadeLimit.addEventListener("change", updateRuntime);
els.messageInput.addEventListener("input", updateMentionSuggestions);
els.messageInput.addEventListener("click", updateMentionSuggestions);
els.messageInput.addEventListener("keydown", handleMentionKeydown);
els.messageInput.addEventListener("blur", () => setTimeout(hideMentionSuggestions, 120));
els.mentionSuggestions.addEventListener("mousedown", (event) => {
  event.preventDefault();
});
els.mentionSuggestions.addEventListener("click", (event) => {
  const option = event.target.closest("[data-index]");
  if (!option) return;
  completeMention(Number(option.dataset.index));
});
els.activityHint.addEventListener("click", async () => {
  els.activityPanel.classList.remove("hidden");
  await renderActivityPanel(currentState?.activity?.agent_id);
});

loadState();
setInterval(loadState, 1500);
