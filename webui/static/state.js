const preferences = loadPreferences();
applyTheme(preferences.theme);

export const state = {
  data: null,
  selectedThreadId: null,
  selectedAgentId: "manager",
  view: "columns",
  syncScroll: false,
  live: true,
  formatMarkdown: preferences.formatMarkdown,
  theme: preferences.theme,
  search: "",
  loading: false,
  pollTimer: null,
  openDetails: new Map(),
  selectedColumnIds: null,
  drawerRunId: null,
  activeRunId: null,
  tempRunIds: [],
  taskRunCache: new Map(),
  taskRunPromises: new Map(),
};

export function resetRunState() {
  state.drawerRunId = null;
  state.activeRunId = null;
  state.tempRunIds = [];
  state.taskRunCache = new Map();
  state.taskRunPromises = new Map();
}

export function resetColumnSelection() {
  state.selectedColumnIds = null;
}

export function setFormatMarkdown(enabled) {
  state.formatMarkdown = Boolean(enabled);
  savePreference("formatMarkdown", state.formatMarkdown);
}

export function setTheme(theme) {
  state.theme = normalizeTheme(theme);
  applyTheme(state.theme);
  savePreference("theme", state.theme);
}

function loadPreferences() {
  return {
    formatMarkdown: loadBooleanPreference("formatMarkdown", true),
    theme: loadThemePreference(),
  };
}

function applyTheme(theme) {
  if (typeof document === "undefined") return;
  document.documentElement.dataset.theme = normalizeTheme(theme);
}

function loadThemePreference() {
  try {
    const value = localStorage.getItem(preferenceKey("theme"));
    return normalizeTheme(value);
  } catch {
    return "dark";
  }
}

function normalizeTheme(theme) {
  return theme === "light" ? "light" : "dark";
}

function loadBooleanPreference(key, fallback) {
  try {
    const value = localStorage.getItem(preferenceKey(key));
    return value === null ? fallback : value === "true";
  } catch {
    return fallback;
  }
}

function savePreference(key, value) {
  try {
    localStorage.setItem(preferenceKey(key), String(value));
  } catch {
    // Preferences are optional; rendering should keep working if storage is blocked.
  }
}

function preferenceKey(key) {
  return `agent-history:${key}`;
}
