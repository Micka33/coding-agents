import { renderMarkdown } from "./markdown.js";
import { escapeAttr, escapeHtml, hashString, htmlToElement, prettyJson } from "./utils.js";

export function createMessageElement(message, agent, maps, context, openDetails = new Map()) {
  const element = htmlToElement(renderMessage(message, agent, maps, context));
  restoreDetailsState(element, context.openDetails, openDetails);
  return element;
}

export function messageKey(agent, message) {
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

export function messageSignature(message, maps, context) {
  const relatedResults = (message.toolCalls || []).map((call) => {
    const result = maps?.byToolCallId.get(call.id);
    const run = call.runId ? context.taskRunById.get(call.runId) : null;
    return {
      callId: call.id,
      resultId: result?.id,
      resultText: result?.contentText,
      resultTimestamp: result?.timestamp?.epochMs,
      runId: call.runId,
      runStats: run?.stats || call.runStats,
    };
  });
  return hashString(
    JSON.stringify({
      message,
      relatedResults,
      activeRunId: context.activeRunId,
      formatMarkdown: context.formatMarkdown,
      tempRunIds: context.tempRunIds || [],
    }),
  );
}

export function captureDetailsState(root) {
  const detailsState = new Map();
  root.querySelectorAll("details[data-detail-key]").forEach((details) => {
    detailsState.set(details.dataset.detailKey, details.open);
  });
  return detailsState;
}

export function rememberDetailsState(detailsState, openDetails) {
  detailsState.forEach((open, key) => openDetails.set(key, open));
}

export function restoreDetailsState(root, openDetails, overrides = new Map()) {
  root.querySelectorAll("details[data-detail-key]").forEach((details) => {
    const key = details.dataset.detailKey;
    if (overrides.has(key)) {
      details.open = overrides.get(key);
    } else if (openDetails.has(key)) {
      details.open = openDetails.get(key);
    }
  });
}

function renderMessage(message, agent, maps, context) {
  const key = messageKey(agent, message);
  const signature = messageSignature(message, maps, context);
  if (message.rawType === "ConversationMarker") {
    return renderConversationBoundary(message, key, signature);
  }
  if (message.rawType === "TaskRunMarker") {
    return renderTaskRunMarker(message, key, signature);
  }

  const speaker = speakerLabel(message, agent);
  const time = message.timestamp?.epochMs ? formatTime(message.timestamp.epochMs) : "";
  const accent = agent.accent || agent.id;
  const selectedRunClass = messageContainsRun(message, context.activeRunId) ? "selected-run-source" : "";
  const renderedBlocks = message.blocks
    .map((block, index) => ({
      html: renderBlock(block, message, agent, index, context),
      internal: isInternalBlock(block),
    }))
    .filter((block) => block.html);
  const internalBlocks = renderedBlocks.filter((block) => block.internal).map((block) => block.html).join("");
  const cardBlocks = renderedBlocks.filter((block) => !block.internal).map((block) => block.html).join("");
  const calls = message.toolCalls
    .map((call, index) => renderToolCall(call, maps?.byToolCallId.get(call.id), message, agent, index, context))
    .join("");
  const fallback = !renderedBlocks.length && !calls && message.contentText
    ? renderTextBlock(message.contentText, context)
    : "";
  const internalBody = message.type === "tool"
    ? renderToolResultMessage(message, agent)
    : `${internalBlocks}${calls}`;
  const cardBody = message.type === "tool" ? "" : `${cardBlocks}${fallback}`;
  const header = `
      <div class="message-header">
        <div class="speaker">${escapeHtml(speaker)}</div>
        <time class="timestamp">${escapeHtml(time)}</time>
      </div>
    `;
  const card = cardBody
    ? `
      <div class="${messageCardClass(accent, message, selectedRunClass)}">
        ${header}
        ${cardBody}
      </div>
    `
    : "";
  const shellClass = internalBody ? (card ? " mixed-event" : " internal-event") : "";

  if (shellClass) {
    return `
      <article class="message event-shell${shellClass}${selectedRunClass ? ` ${selectedRunClass}` : ""}" data-message-id="${escapeAttr(message.id)}" data-message-key="${escapeAttr(key)}" data-render-hash="${escapeAttr(signature)}" data-ts="${message.timestamp?.epochMs || ""}">
        ${internalBody}
        ${card}
      </article>
    `;
  }

  return `
    <article class="${messageClass(accent, message, selectedRunClass)}" data-message-id="${escapeAttr(message.id)}" data-message-key="${escapeAttr(key)}" data-render-hash="${escapeAttr(signature)}" data-ts="${message.timestamp?.epochMs || ""}">
      ${header}
      ${cardBody}
    </article>
  `;
}

function renderConversationBoundary(message, key, signature) {
  const lines = String(message.contentText || "")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
  const title = lines[0] || "Conversation déléguée";
  const source = lines[1] || "";
  const toolName = source.match(/\bvia\s+(.+)$/)?.[1];
  const label = toolName ? `Appel via ${toolName}` : source || title;
  const fullText = lines.join("\n");
  return `
    <article class="message conversation-boundary" title="${escapeAttr(fullText)}" data-message-id="${escapeAttr(message.id)}" data-message-key="${escapeAttr(key)}" data-render-hash="${escapeAttr(signature)}" data-ts="">
      <div class="conversation-boundary-line"></div>
      <div class="conversation-boundary-label">${escapeHtml(label)}</div>
    </article>
  `;
}

function renderTaskRunMarker(message, key, signature) {
  const source = message.sourceAgent || "agent appelant";
  const target = message.targetAgent || message.agentId || "agent";
  const prompt = String(message.promptText || "").trim();
  const checkpoint = message.checkpointNs || "";
  const title = `Appel de ${source} vers ${target}`;
  const fullText = [title, checkpoint, prompt].filter(Boolean).join("\n");
  const promptDetails = prompt
    ? `
      <details class="task-run-input" data-detail-key="${escapeAttr(`${key}:input`)}">
        <summary>Prompt reçu</summary>
        <pre class="tool-pre">${escapeHtml(prompt)}</pre>
      </details>
    `
    : "";

  return `
    <article class="message task-run-marker" title="${escapeAttr(fullText)}" data-message-id="${escapeAttr(message.id)}" data-message-key="${escapeAttr(key)}" data-render-hash="${escapeAttr(signature)}" data-ts="${message.timestamp?.epochMs || ""}">
      <div class="task-run-marker-line"></div>
      <div class="task-run-marker-body">
        <div class="task-run-marker-heading">
          <span class="task-run-marker-title">${escapeHtml(title)}</span>
          <span class="badge disposable">agent non persistant</span>
        </div>
        ${promptDetails}
      </div>
    </article>
  `;
}

function messageClass(accent, message, selectedRunClass) {
  return [
    "message",
    accent,
    message.type === "human" ? "human" : "",
    message.type === "tool" ? "tool" : "",
    selectedRunClass,
  ]
    .filter(Boolean)
    .join(" ");
}

function messageCardClass(accent, message, selectedRunClass) {
  return [
    "message-card",
    accent,
    message.type === "human" ? "human" : "",
    selectedRunClass,
  ]
    .filter(Boolean)
    .join(" ");
}

function isInternalBlock(block) {
  return block.type === "reasoning" || block.phase === "commentary";
}

function renderBlock(block, message, agent, index, context) {
  if (block.type === "reasoning") {
    const text = block.summary || block.text;
    if (!text) return "";
    const detailKey = `${messageKey(agent, message)}:reasoning:${index}`;
    return `
      <details class="thinking" data-detail-key="${escapeAttr(detailKey)}" open>
        <summary><span>Réflexion</span></summary>
        <div class="thinking-body">
          ${renderTextBlock(text, context)}
        </div>
      </details>
    `;
  }

  if (!block.text) return "";
  return renderTextBlock(block.text, context, { phase: block.phase });
}

function renderTextBlock(text, context, options = {}) {
  const phase = options.phase ? `<span class="badge text-phase">${escapeHtml(options.phase)}</span>` : "";
  if (!context.formatMarkdown) {
    return `<div class="text-block">${phase}${phase ? "\n" : ""}${escapeHtml(text)}</div>`;
  }

  return `
    <div class="text-block markdown-block">
      ${phase}
      <div class="markdown-body">${renderMarkdown(text)}</div>
    </div>
  `;
}

function renderToolResultMessage(message, agent) {
  const detailKey = `${messageKey(agent, message)}:tool-result`;
  const resultText = message.contentText || message.blocks.map((block) => block.text || block.summary || "").filter(Boolean).join("\n");
  const name = message.name || message.rawType || "résultat";
  return `
    <details class="tool-call generic-tool tool-result" data-detail-key="${escapeAttr(detailKey)}">
      <summary>
        <span class="call-heading">
          <span class="call-name">Résultat ${escapeHtml(name)}</span>
          <span class="badge">outil</span>
        </span>
      </summary>
      <div class="tool-body">
        <pre class="tool-pre">${escapeHtml(resultText || "Résultat vide.")}</pre>
      </div>
    </details>
  `;
}

function renderToolCall(call, result, message, agent, index, context) {
  const detailKey = `${messageKey(agent, message)}:tool:${call.id || `${index}:${call.name}`}`;
  const display = toolCallDisplay(call);
  const pathSummary = display.isSpecific ? "" : renderToolPathSummary(toolCallPaths(call));

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
    return renderDisposableAgentCall(call, result, detailKey, context);
  }

  const resultText = result?.contentText || "Résultat pas encore disponible.";
  return `
    <details class="tool-call generic-tool" data-detail-key="${escapeAttr(detailKey)}">
      <summary>
        <span class="call-heading">
          ${renderToolCallDisplay(display)}
          ${pathSummary}
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

function toolCallDisplay(call) {
  const name = String(call.name || "outil");
  const args = toolCallArgs(call);
  const normalizedName = name.toLowerCase();

  if (normalizedName === "grep") {
    const pattern = formatInlineValue(args.pattern || args.query || "");
    const target = formatGrepTarget(args.path, args.glob);
    const label = `grep ${pattern || "<pattern>"} in ${target}`;
    return { isSpecific: true, kind: "grep", pattern: pattern || "<pattern>", target, title: label };
  }

  if (normalizedName === "execute") {
    const command = oneLine(args.command || args.cmd || args.shell || "");
    const label = command ? `execute ${command}` : "execute";
    return { isSpecific: true, kind: "execute", command, title: command || label };
  }

  return { isSpecific: false, kind: "default", label: name, title: name };
}

function renderToolCallDisplay(display) {
  if (display.kind === "grep") {
    return `
      <span class="tool-summary tool-summary-grep" title="${escapeAttr(display.title)}">
        <span class="tool-summary-action">grep</span>
        <span class="tool-summary-token tool-summary-pattern">${escapeHtml(display.pattern)}</span>
        <span class="tool-summary-muted">in</span>
        <span class="tool-summary-token tool-summary-target">${escapeHtml(display.target)}</span>
      </span>
    `;
  }

  if (display.kind === "execute") {
    return `
      <span class="tool-summary tool-summary-execute" title="${escapeAttr(display.title)}">
        <span class="tool-summary-action">execute</span>
        <span class="tool-summary-command">${escapeHtml(display.command || "commande vide")}</span>
      </span>
    `;
  }

  return `<span class="call-name" title="${escapeAttr(display.title)}">${escapeHtml(display.label)}</span>`;
}

function toolCallArgs(call) {
  if (call.args && typeof call.args === "object") return call.args;
  return parseJsonObject(call.rawArguments) || {};
}

function formatGrepTarget(path, glob) {
  const normalizedPath = oneLine(path || ".");
  const normalizedGlob = oneLine(glob || "");
  if (!normalizedGlob) return normalizedPath;
  if (!normalizedPath || normalizedPath === ".") return normalizedGlob;
  return `${normalizedPath.replace(/\/+$/, "")}/${normalizedGlob.replace(/^\/+/, "")}`;
}

function formatInlineValue(value) {
  const text = oneLine(value);
  if (!text) return "";
  return /\s/.test(text) ? JSON.stringify(text) : text;
}

function oneLine(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function renderDisposableAgentCall(call, result, detailKey, context) {
  const target = call.targetAgent || "agent";
  const description = call.args?.description || prettyJson(call.args);
  const resultText = result?.contentText || "Résultat pas encore disponible.";
  const run = call.runId ? context.taskRunById.get(call.runId) : null;
  const stats = call.runStats || run?.stats || {};
  const isColumnOpen = Boolean(call.runId && context.tempRunIds?.includes(call.runId));
  const openAttrs = call.runId
    ? `data-action="open-run-drawer" data-run-id="${escapeAttr(call.runId)}"`
    : "disabled";
  const columnButton = call.runId
    ? `
      <button class="mini-button" type="button" data-action="${isColumnOpen ? "close-run-column" : "open-run-column"}" data-run-id="${escapeAttr(call.runId)}">
        ${isColumnOpen ? "Retirer" : "Colonne"}
      </button>
    `
    : "";

  return `
    <div class="tool-call disposable-agent task-call">
      <div class="task-call-header">
        <button class="task-open-button" type="button" ${openAttrs}>
          <span class="call-name">Appel ${escapeHtml(target)}</span>
          <span class="badge disposable">agent non persistant</span>
          <span class="run-metrics">${escapeHtml(runMetrics(stats))}</span>
        </button>
        ${columnButton}
      </div>
      <details class="task-call-payload" data-detail-key="${escapeAttr(detailKey)}">
        <summary>
          <span>Input et résultat</span>
          ${call.runId ? "" : `<span class="badge">historique indisponible</span>`}
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
    </div>
  `;
}

function renderToolPathSummary(paths) {
  if (!paths.length) return "";
  const [firstPath, ...rest] = paths;
  const fullText = paths.join("\n");
  const suffix = rest.length ? ` +${rest.length}` : "";
  return `<span class="call-path" title="${escapeAttr(fullText)}">${escapeHtml(firstPath)}${escapeHtml(suffix)}</span>`;
}

function toolCallPaths(call) {
  const paths = [];
  const seen = new Set();
  const sources = [call.args, parseJsonObject(call.rawArguments)];

  sources.forEach((source) => collectPathCandidates(source, paths, seen));
  return paths;
}

function collectPathCandidates(value, paths, seen, parentKey = "") {
  if (!value || paths.length >= 4) return;

  if (Array.isArray(value)) {
    value.forEach((item) => collectPathCandidates(item, paths, seen, parentKey));
    return;
  }

  if (typeof value !== "object") {
    if (isPathKey(parentKey) && isDisplayablePath(value)) addPathCandidate(String(value), paths, seen);
    return;
  }

  Object.entries(value).forEach(([key, entry]) => {
    if (paths.length >= 4) return;
    if (isPathKey(key) && isDisplayablePath(entry)) {
      addPathCandidate(String(entry), paths, seen);
      return;
    }
    if (isPathContainerKey(key) || typeof entry === "object") {
      collectPathCandidates(entry, paths, seen, key);
    }
  });
}

function addPathCandidate(value, paths, seen) {
  const path = value.trim();
  if (!path || seen.has(path)) return;
  seen.add(path);
  paths.push(path);
}

function isPathKey(key) {
  return [
    "absolute_path",
    "destination",
    "file",
    "file_path",
    "filepath",
    "filename",
    "path",
    "relative_path",
    "target_file",
    "target_path",
    "write_path",
  ].includes(String(key || "").replaceAll("-", "_").toLowerCase());
}

function isPathContainerKey(key) {
  return ["files", "paths", "edits", "changes", "operations"].includes(
    String(key || "").replaceAll("-", "_").toLowerCase(),
  );
}

function isDisplayablePath(value) {
  if (typeof value !== "string") return false;
  const text = value.trim();
  if (!text || text.length > 300 || text.includes("\n")) return false;
  return text.includes("/") || text.includes("\\") || /\.[A-Za-z0-9]{1,12}$/.test(text);
}

function parseJsonObject(value) {
  if (typeof value !== "string" || !value.trim()) return null;
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === "object" ? parsed : null;
  } catch {
    return null;
  }
}

function messageContainsRun(message, runId) {
  return Boolean(runId && message.toolCalls.some((call) => call.runId === runId));
}

function speakerLabel(message, agent) {
  if (message.type === "human") {
    if (agent.kind === "disposable-run" || agent.kind === "task-agent-group") return "Prompt reçu";
    if (message.senderAgentId) return displayAgentName(message.senderAgentId);
    return agent.id === "manager" || agent.accent === "manager" ? "Humain" : "Manager";
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

function runMetrics(stats) {
  const messages = stats.messages || 0;
  const toolCalls = stats.toolCalls || 0;
  return `${messages} msg · ${toolCalls} outils`;
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
