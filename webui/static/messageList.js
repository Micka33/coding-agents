import { renderableMessages } from "./data.js";
import {
  captureDetailsState,
  createMessageElement,
  messageKey,
  messageSignature,
  rememberDetailsState,
} from "./messages.js";
import { directChildren, htmlToElement } from "./utils.js";

export function handleDetailsToggle(event, openDetails) {
  const details = event.target;
  if (!(details instanceof HTMLDetailsElement)) return;
  const key = details.dataset.detailKey;
  if (key) openDetails.set(key, details.open);
}

export function reconcileMessageList(container, agent, maps, context, options = {}) {
  const messages =
    "messages" in options ? options.messages : renderableMessages(agent, maps, context.search || "");
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
    const signature = messageSignature(message, maps, context);
    let element = existing.get(key);

    if (!element) {
      element = createMessageElement(message, agent, maps, context);
    } else if (element.dataset.renderHash !== signature) {
      const openDetails = captureDetailsState(element);
      rememberDetailsState(openDetails, context.openDetails);
      const replacement = createMessageElement(message, agent, maps, context, openDetails);
      element.replaceWith(replacement);
      element = replacement;
    }

    container.appendChild(element);
  });
}
