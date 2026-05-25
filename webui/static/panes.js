import { reconcileMessageList } from "./messageList.js";
import { htmlToElement } from "./utils.js";

export function clearMessagePaneHost(root) {
  root.innerHTML = "";
  delete root.dataset.messagePaneKey;
  delete root.dataset.messagePaneMode;
}

export function renderMessagePane(root, agent, maps, context, options = {}) {
  ensureMessagePaneShell(root, options);
  if (options.updateChrome) options.updateChrome(root);

  const list = options.listSelector === null ? root : root.querySelector(options.listSelector || ".message-list");
  if (!list || !agent) return list;

  if (options.scrollKey) list.dataset.scrollKey = options.scrollKey;

  const reconcileOptions = { showEmpty: options.showEmpty !== false };
  if ("messages" in options) reconcileOptions.messages = options.messages;
  reconcileMessageList(list, agent, maps, context, reconcileOptions);
  return list;
}

export function replacePanePart(root, selector, markup, placement = "prepend") {
  const next = htmlToElement(markup);
  const current = root.querySelector(selector);
  if (current) {
    current.replaceWith(next);
    return next;
  }

  if (placement === "append") root.append(next);
  else root.prepend(next);
  return next;
}

function ensureMessagePaneShell(root, options) {
  if (!options.shellHtml) return;

  const mode = options.shellMode || "messages";
  if (root.dataset.messagePaneKey === options.shellKey && root.dataset.messagePaneMode === mode) return;

  root.innerHTML = options.shellHtml;
  root.dataset.messagePaneKey = options.shellKey || "";
  root.dataset.messagePaneMode = mode;
}
