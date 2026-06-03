import "@testing-library/jest-dom/vitest"

class ResizeObserverMock {
  disconnect() {}

  observe() {}

  unobserve() {}
}

globalThis.ResizeObserver ??= ResizeObserverMock as unknown as typeof ResizeObserver
