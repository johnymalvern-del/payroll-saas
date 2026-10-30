import "@testing-library/jest-dom/vitest";

// jsdom does not implement matchMedia; Mantine components call it.
// The polyfill returns a minimal MediaQueryList that reports "not matching"
// so Mantine falls back to its smallest breakpoint. Good enough for tests
// that don't assert on responsive behaviour.
if (typeof window !== "undefined" && typeof window.matchMedia !== "function") {
  const createMql = (query: string): MediaQueryList => {
    const mql = {
      matches: false,
      media: query,
      onchange: null,
      addListener: () => undefined,
      removeListener: () => undefined,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      dispatchEvent: () => false,
    };
    return mql as unknown as MediaQueryList;
  };
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    configurable: true,
    value: (query: string) => createMql(query),
  });
}

// jsdom does not implement ResizeObserver; Mantine ScrollArea and Table use it.
if (typeof window !== "undefined" && typeof (window as unknown as { ResizeObserver?: unknown }).ResizeObserver !== "function") {
  class ResizeObserverStub {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  (window as unknown as { ResizeObserver: unknown }).ResizeObserver =
    ResizeObserverStub;
  (globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver =
    ResizeObserverStub;
}

// jsdom does not implement IntersectionObserver either; cheap safety net.
if (
  typeof window !== "undefined" &&
  typeof (window as unknown as { IntersectionObserver?: unknown }).IntersectionObserver !== "function"
) {
  class IntersectionObserverStub {
    root = null;
    rootMargin = "";
    thresholds: number[] = [];
    observe() {}
    unobserve() {}
    disconnect() {}
    takeRecords() {
      return [];
    }
  }
  (window as unknown as { IntersectionObserver: unknown }).IntersectionObserver =
    IntersectionObserverStub;
  (globalThis as unknown as { IntersectionObserver: unknown }).IntersectionObserver =
    IntersectionObserverStub;
}
