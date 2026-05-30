const els = {
  roomMeta: document.querySelector("#roomMeta"),
  messages: document.querySelector("#messages"),
  hookToggle: document.querySelector("#hookToggle"),
  cascadeLimit: document.querySelector("#cascadeLimit"),
  composer: document.querySelector("#composer"),
  messageInput: document.querySelector("#messageInput"),
  fileInput: document.querySelector("#fileInput"),
  activityHint: document.querySelector("#activityHint"),
  activityPanel: document.querySelector("#activityPanel"),
};

let currentState = null;

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

els.composer.addEventListener("submit", sendMessage);
els.hookToggle.addEventListener("change", updateRuntime);
els.cascadeLimit.addEventListener("change", updateRuntime);
els.activityHint.addEventListener("click", async () => {
  els.activityPanel.classList.remove("hidden");
  await renderActivityPanel(currentState?.activity?.agent_id);
});

loadState();
setInterval(loadState, 1500);
