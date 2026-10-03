/* Service worker: lets the installed app open offline with the last data it saw.

   Strategy: network first, cache as fallback. Fresh data whenever you're online; the
   last good copy when you're not. Navigations go to the network untouched (so a login
   page in front of the site, such as Cloudflare Access, keeps working); only a failed
   navigation falls back to the cached page. */
const CACHE = "fantasy-nfl-v1";
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
