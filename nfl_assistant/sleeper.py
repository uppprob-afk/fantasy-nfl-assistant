"""Polite client for the public Sleeper API (no auth).

- Waits a little between calls and retries with backoff on errors / rate limits.
- players/nfl (~15MB) is downloaded at most once per run and cached on disk.
"""

import json
import time
from pathlib import Path

import httpx

RETRY_STATUS = {429}           # plus every 5xx (incl. Cloudflare's 520-530 when Sleeper is briefly down)


class SleeperClient:
    def __init__(self, base_url: str, delay_seconds: float = 0.4, max_retries: int = 4,
                 timeout_seconds: float = 30, cache_dir: Path | None = None):
        self.base_url = base_url.rstrip("/")
        self.delay = delay_seconds
        self.max_retries = max_retries
        self.cache_dir = cache_dir
        self._http = httpx.Client(timeout=timeout_seconds,
                                  headers={"User-Agent": "fantasy-nfl-assistant (personal use)"})
        self._last_call = 0.0
        self._players: dict | None = None
        self.calls = 0

    def get(self, path: str, params: dict | None = None):
        url = f"{self.base_url}/{path.lstrip('/')}"
        for attempt in range(self.max_retries + 1):
            wait = self.delay - (time.monotonic() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.monotonic()
            self.calls += 1
            try:
                resp = self._http.get(url, params=params)
                if resp.status_code not in RETRY_STATUS and resp.status_code < 500:
                    resp.raise_for_status()
                    return resp.json()
                problem = f"HTTP {resp.status_code}"
            except httpx.TransportError as exc:
                problem = repr(exc)
            if attempt == self.max_retries:
                raise RuntimeError(f"Sleeper API failed after {attempt + 1} tries: {url} ({problem})")
            time.sleep(2 ** attempt)  # 1s, 2s, 4s, 8s

    # --- endpoints -------------------------------------------------------
    def state(self):
        return self.get("state/nfl")

    def league(self, league_id):
        return self.get(f"league/{league_id}")

    def user(self, username):
        return self.get(f"user/{username}")

    def rosters(self, league_id):
        return self.get(f"league/{league_id}/rosters")

    def users(self, league_id):
        return self.get(f"league/{league_id}/users")

    def matchups(self, league_id, week):
        return self.get(f"league/{league_id}/matchups/{week}") or []

    def transactions(self, league_id, week):
        return self.get(f"league/{league_id}/transactions/{week}") or []

    def trending(self, kind: str, lookback_hours: int = 48, limit: int = 50):
        return self.get(f"players/nfl/trending/{kind}",
                        params={"lookback_hours": lookback_hours, "limit": limit}) or []

    def players(self, max_age_hours: float = 1) -> dict:
        """All NFL players. Fetched at most once per run; reuses a fresh disk cache."""
        if self._players is not None:
            return self._players
        cache = self.cache_dir / "players_nfl.json" if self.cache_dir else None
        if cache and cache.exists() and time.time() - cache.stat().st_mtime < max_age_hours * 3600:
            self._players = json.loads(cache.read_text(encoding="utf-8"))
            return self._players
        self._players = self.get("players/nfl")
        if cache:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(self._players), encoding="utf-8")
        return self._players
