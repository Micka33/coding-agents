export const state = {
  data: null,
  selectedThreadId: null,
  selectedAgentId: "manager",
  view: "columns",
  syncScroll: false,
  live: true,
  search: "",
  loading: false,
  pollTimer: null,
  openDetails: new Map(),
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
