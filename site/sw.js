/* Service worker: fast opens and offline use.

   - Data files (data/*.js): shown straight from the cache, then refreshed in the background;
     if the fresh copy differs, open pages get a "new data" message (stale-while-revalidate).
   - App files: network first, cache as fallback.
   - Navigations go to the network untouched (so a login page in front of the site, such as
     Cloudflare Access, keeps working); only a failed navigation falls back to the cached page. */
const CACHE = "fantasy-nfl-v2";
const SHELL = ["./", "./index.html", "./styles.css", "./app.js", "./manifest.webmanifest",
  "./icons/icon-192.png", "./icons/icon-512.png", "./icons/apple-touch-icon.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== self.location.origin) return;
  if (url.searchParams.has("ping")) return;   // connectivity check: always hits the network

  if (req.mode === "navigate") {
    event.respondWith(fetch(req).catch(() => caches.match("./index.html")));
    return;
  }
  if (url.pathname.includes("/data/") && url.pathname.endsWith(".js")) {
    event.respondWith(staleWhileRevalidate(event, req));
    return;
  }
  event.respondWith(
    fetch(req)
      .then((res) => {
        // Only cache real, same-origin successes (not login redirects or errors).
        if (res.ok && res.type === "basic" && !res.redirected) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy));
        }
        return res;
      })
      .catch(() => caches.match(req, { ignoreSearch: true }))
  );
});

const ok = (res) => res && res.ok && res.type === "basic" && !res.redirected;

async function staleWhileRevalidate(event, req) {
  const cache = await caches.open(CACHE);
  const cached = await cache.match(req, { ignoreSearch: true });
  const refresh = fetch(req).then(async (res) => {
    if (!ok(res)) return res;
    const fresh = res.clone();
    if (cached) {
      const [a, b] = await Promise.all([cached.clone().text(), res.clone().text()]);
      if (a !== b) {
        const clients = await self.clients.matchAll({ type: "window" });
        clients.forEach((c) => c.postMessage({ type: "data-updated", file: new URL(req.url).pathname }));
      }
    }
    await cache.put(req, fresh);
    return res;
  }).catch(() => cached);
  if (cached) {
    event.waitUntil(refresh);
    return cached;
  }
  return refresh;
}
