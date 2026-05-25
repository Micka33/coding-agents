const preferences = loadPreferences();

export const state = {
  data: null,
  selectedThreadId: null,
  selectedAgentId: "manager",
  view: "columns",
  syncScroll: false,
  live: true,
  formatMarkdown: preferences.formatMarkdown,
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

function loadPreferences() {
  return {
    formatMarkdown: loadBooleanPreference("formatMarkdown", true),
  };
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
