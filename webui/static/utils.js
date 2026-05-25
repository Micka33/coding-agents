export function directChildren(element) {
  return Array.from(element?.children || []);
}

export function insertChildAt(parent, child, index) {
  const current = parent.children[index] || null;
  if (current !== child) parent.insertBefore(child, current);
}

export function htmlToElement(markup) {
  const template = document.createElement("template");
  template.innerHTML = markup.trim();
  return template.content.firstElementChild;
}

export function hashString(value) {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(36);
}

export function capturePinnedScrollers() {
  const pinned = new Map();
  document.querySelectorAll(".scroll-region").forEach((element) => {
    const key = element.dataset.scrollKey;
    if (!key) return;
    pinned.set(key, {
      contentSignature: scrollContentSignature(element),
      element,
      nearBottom: isNearBottom(element),
      scrollTop: element.scrollTop,
    });
  });
  return pinned;
}

export function restorePinnedScrollers(pinned, firstLoad = false) {
  const apply = () => {
    document.querySelectorAll(".scroll-region").forEach((element) => {
      const key = element.dataset.scrollKey;
      const previous = pinned.get(key);
      if (
        previous &&
        previous.element === element &&
        scrollContentSignature(element) === previous.contentSignature
      ) return;
      if (previous && didScrollAfterCapture(element, previous)) return;

      const shouldPin = firstLoad || !previous || previous.nearBottom;
      if (shouldPin) {
        scrollRegionToBottom(element);
      } else {
        restoreScrollRegion(element, previous);
      }
      if (previous) previous.appliedScrollTop = element.scrollTop;
    });
  };
  requestAnimationFrame(() => {
    apply();
    setTimeout(apply, 50);
    setTimeout(apply, 250);
  });
}

export function restoreScrollRegion(element, previous) {
  const maxScrollTop = Math.max(0, element.scrollHeight - element.clientHeight);
  element.scrollTop = Math.min(previous.scrollTop, maxScrollTop);
}

export function scrollRegionToBottom(element) {
  element.scrollTop = Math.max(0, element.scrollHeight - element.clientHeight);
  const lastChild = element.lastElementChild;
  if (lastChild && typeof lastChild.scrollIntoView === "function") {
    lastChild.scrollIntoView({ block: "end", inline: "nearest" });
  }
}

export function isNearBottom(element) {
  return element.scrollHeight - element.clientHeight - element.scrollTop < 90;
}

function didScrollAfterCapture(element, previous) {
  const expectedScrollTop = previous.appliedScrollTop ?? previous.scrollTop;
  return Math.abs(element.scrollTop - expectedScrollTop) > 2;
}

function scrollContentSignature(element) {
  const children = Array.from(element.children);
  const firstKey = children[0]?.dataset.messageKey || children[0]?.dataset.rowKey || "";
  const lastKey = children.at(-1)?.dataset.messageKey || children.at(-1)?.dataset.rowKey || "";
  const firstHash = children[0]?.dataset.renderHash || "";
  const lastHash = children.at(-1)?.dataset.renderHash || "";
  return [
    children.length,
    firstKey,
    firstHash,
    lastKey,
    lastHash,
  ].join(":");
}

export function formatTime(epochMs) {
  return new Intl.DateTimeFormat(undefined, {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(epochMs));
}

export function formatTimelineTime(epochMs) {
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

export function prettyJson(value) {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

export function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

export function escapeAttr(value) {
  return escapeHtml(value).replaceAll("`", "&#096;");
}
