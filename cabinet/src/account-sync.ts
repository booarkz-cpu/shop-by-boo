// One account state for the cabinet and the Telegram Mini App: GET /api/me/sync long-polls until the
// subscription, wallet, pending payments or server list change, then the page reloads its data.
// A paid order therefore appears without a manual refresh, whichever client the customer paid in.

export type SyncFetch = (url: string, init: RequestInit) => Promise<Response>;

export function watchAccount(api: string, onChange: () => void, fetcher: SyncFetch = (u, i) => fetch(u, i)): () => void {
  let stopped = false;
  let version = "";
  let ctrl: AbortController | null = null;
  const pause = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));
  (async () => {
    let failures = 0;
    while (!stopped) {
      if (typeof document !== "undefined" && document.visibilityState === "hidden") { await pause(5000); continue; }
      ctrl = new AbortController();
      const timer = setTimeout(() => ctrl?.abort(), 35000);
      try {
        const query = version ? `?since=${encodeURIComponent(version)}&wait=25` : "";
        const r = await fetcher(`${api}/api/me/sync${query}`, {credentials: "include", signal: ctrl.signal});
        if (r.status === 200) {
          const body = await r.json();
          const changed = Boolean(version) && body.version !== version;
          version = body.version || "";
          if (changed) onChange();
        } else if (r.status !== 304) {
          throw new Error(`HTTP ${r.status}`);
        }
        failures = 0;
      } catch {
        if (stopped) break;
        failures += 1;
        await pause(Math.min(60000, 2000 * 2 ** Math.min(failures, 5)));
      } finally {
        clearTimeout(timer);
      }
    }
  })();
  return () => { stopped = true; ctrl?.abort(); };
}
