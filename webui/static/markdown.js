import DOMPurify from "./vendor/purify.es.mjs";
import { marked } from "./vendor/marked.esm.js";
import { escapeHtml } from "./utils.js";

marked.setOptions({
  async: false,
  breaks: true,
  gfm: true,
  silent: true,
});

const sanitizeOptions = {
  FORBID_TAGS: [
    "button",
    "embed",
    "form",
    "iframe",
    "img",
    "input",
    "object",
    "script",
    "select",
    "style",
    "textarea",
  ],
};

export function renderMarkdown(text) {
  if (!text) return "";
  try {
    const rawHtml = marked.parse(String(text));
    const sanitized = DOMPurify.sanitize(rawHtml, sanitizeOptions);
    return hardenLinks(sanitized);
  } catch {
    return escapeHtml(text);
  }
}

function hardenLinks(html) {
  const template = document.createElement("template");
  template.innerHTML = html;
  template.content.querySelectorAll("a[href]").forEach((link) => {
    link.setAttribute("target", "_blank");
    link.setAttribute("rel", "noreferrer noopener");
  });
  return template.innerHTML;
}
