// The Messenger bus the operator is currently looking at.
//
// Shared by the Agents page (which lets you choose it) and the Dashboard
// (which counts agents on it). Keeping the key in one module is the point:
// the Dashboard's "Agents Online" card used to count a hardcoded
// "head-agent" bus that no real deployment uses, so it read 0 against a
// perfectly healthy fleet while the Agents page - looking at the bus you
// actually chose - listed every agent correctly.
//
// Per-browser rather than server-side: which bus you are looking at is a
// view preference, not deployment state, and it needs no API surface to
// store. The trade-off is that it does not follow you to another browser.

export const BUS_STORAGE_KEY = "scarlet-composer.agents.bus";

// A conventional name from scarlets' own examples. The harness derives its
// bus from HEAD_BUS, or f"{APP_ID}_headagent" when that is unset, so this
// matches a real deployment only by coincidence - it is a starting point
// for the Agents page's input, not an expectation.
export const DEFAULT_BUS = "head-agent";

/** The stored bus, or DEFAULT_BUS. Safe on the server and with storage disabled. */
export function readStoredBus(): string {
  if (typeof window === "undefined") return DEFAULT_BUS;
  try {
    return window.localStorage.getItem(BUS_STORAGE_KEY) || DEFAULT_BUS;
  } catch {
    // Private browsing, or storage blocked by policy.
    return DEFAULT_BUS;
  }
}

/** Persist the chosen bus. Silently a no-op if storage is unavailable. */
export function storeBus(bus: string): void {
  try {
    window.localStorage.setItem(BUS_STORAGE_KEY, bus);
  } catch {
    // Not fatal - the choice just will not survive a reload.
  }
}
