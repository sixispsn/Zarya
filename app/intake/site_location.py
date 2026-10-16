"""Optional reference geography. Deliberately independent of engineering inputs.

Public pilot providers are replaceable, cached and globally rate-limited across
workers. No background geocoding, reverse lookup, document upload or telemetry.
"""
from contextlib import closing
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import time
from urllib.parse import urlsplit

import httpx


class GeographyUnavailable(ValueError):
    pass


def endpoint(name: str, default: str) -> str:
    value = os.environ.get(name) or default
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise GeographyUnavailable("Картографический сервис не настроен.")
    return value


def map_config() -> dict:
    if os.environ.get("ZARYA_GEO_ENABLED", "1") != "1":
        raise GeographyUnavailable("Онлайн-карта отключена. Можно ввести координаты вручную.")
    return {
        "tiles": endpoint("ZARYA_MAP_TILES_URL", "https://tile.openstreetmap.org/{z}/{x}/{y}.png"),
        "attribution": os.environ.get("ZARYA_MAP_ATTRIBUTION", "© OpenStreetMap contributors"),
        "attribution_url": endpoint("ZARYA_MAP_ATTRIBUTION_URL", "https://www.openstreetmap.org/copyright"),
        "provider_label": os.environ.get("ZARYA_MAP_PROVIDER_LABEL", "OpenStreetMap"),
    }


class Geography:
    def __init__(self):
        studio = Path(os.environ.get("ZARYA_STUDIO_DIR", str(Path.home() / ".zarya" / "studio")))
        root = Path(os.environ.get("ZARYA_GEO_DIR", str(studio / "_geography")))
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = root / "cache.sqlite3"
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        with closing(sqlite3.connect(self.path, timeout=3)) as db, db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, expires REAL, body TEXT);
                CREATE TABLE IF NOT EXISTS quota (provider TEXT PRIMARY KEY, next_at REAL, day INTEGER, used INTEGER);
            """)

    def fetch(self, provider: str, url: str, params: dict, ttl: int):
        if os.environ.get("ZARYA_GEO_ENABLED", "1") != "1":
            raise GeographyUnavailable("Онлайн-карта отключена. Можно ввести координаты вручную.")
        key = hashlib.sha256(json.dumps([provider, url, params], sort_keys=True).encode()).hexdigest()
        now = time.time()
        # Reserve before I/O: one shared quota per service, not per user/process.
        with closing(sqlite3.connect(self.path, timeout=3)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            cached = db.execute("SELECT body FROM cache WHERE key=? AND expires>?", (key, now)).fetchone()
            if cached:
                return json.loads(cached[0])
            quota = db.execute("SELECT next_at, day, used FROM quota WHERE provider=?", (provider,)).fetchone()
            day = int(now // 86400)
            used = quota[2] if quota and quota[1] == day else 0
            if quota and now < quota[0]:
                raise GeographyUnavailable("Сервис занят. Повторите через пару секунд.")
            if used >= 500:
                raise GeographyUnavailable("Дневной лимит справочного сервиса исчерпан. Координаты можно сохранить без него.")
            db.execute("INSERT OR REPLACE INTO quota VALUES (?,?,?,?)", (provider, now + 1.1, day, used + 1))
        try:
            with httpx.Client(timeout=8, follow_redirects=False, headers={
                "User-Agent": "Zarya/0.02 (+https://zaryaproekt.ru)", "Accept": "application/json",
            }) as client:
                with client.stream("GET", url, params=params) as response:
                    response.raise_for_status()
                    raw = bytearray()
                    for chunk in response.iter_bytes():
                        raw.extend(chunk)
                        if len(raw) > 131072:
                            raise ValueError("Oversize geography response")
                    result = json.loads(raw)
        except (httpx.HTTPError, ValueError):
            raise GeographyUnavailable("Справочный сервис не ответил. Можно сохранить координаты вручную.") from None
        with closing(sqlite3.connect(self.path, timeout=3)) as db, db:
            db.execute("DELETE FROM cache WHERE expires<=?", (now,))
            db.execute("INSERT OR REPLACE INTO cache VALUES (?,?,?)", (key, now + ttl, json.dumps(result)))
            db.execute("DELETE FROM cache WHERE key IN (SELECT key FROM cache ORDER BY expires DESC LIMIT -1 OFFSET 2000)")
        return result

    def search(self, query: str) -> list[dict]:
        url = endpoint("ZARYA_GEOCODER_URL", "https://photon.komoot.io/api/")
        data = self.fetch("search", url, {"q": " ".join(query.split()), "limit": 5}, 7 * 86400)
        rows = []
        try:
            for feature in data["features"][:5]:
                lon, lat = feature["geometry"]["coordinates"]
                if isinstance(lat, bool) or isinstance(lon, bool) or not (-90 <= lat <= 90 and -180 <= lon <= 180):
                    continue
                props = feature["properties"]
                parts = [props.get(key) for key in ("name", "street", "housenumber", "city", "state", "country")]
                label = ", ".join(dict.fromkeys(part for part in parts if isinstance(part, str)))[:400]
                rows.append({"latitude": lat, "longitude": lon, "label": label, "source": "search"})
        except (KeyError, TypeError, ValueError):
            raise GeographyUnavailable("Поиск вернул неполный ответ. Укажите точку на карте или координаты.") from None
        return rows

    def elevation(self, latitude: float, longitude: float) -> dict:
        base = {"source": "Open Topo Data / SRTM30m", "resolution_m": 30,
                "reference_only": True, "retrieved_at": int(time.time())}
        # The selected dataset does not cover the far north. Never replace null
        # with sea level or quietly switch to a different vertical reference.
        if not -60 <= latitude <= 60:
            return {**base, "status": "no_coverage", "metres": None}
        url = endpoint("ZARYA_ELEVATION_URL", "https://api.opentopodata.org/v1/srtm30m")
        data = self.fetch("elevation", url, {"locations": f"{latitude:.6f},{longitude:.6f}"}, 90 * 86400)
        try:
            if data["status"] != "OK" or data["results"][0]["dataset"] != "srtm30m":
                raise ValueError("Unexpected elevation dataset")
            value = data["results"][0]["elevation"]
            if value is not None and (isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not -500 <= value <= 9000):
                raise ValueError("Invalid elevation")
        except (KeyError, IndexError, TypeError, ValueError):
            raise GeographyUnavailable("Не удалось получить справочную высоту.") from None
        return {**base, "status": "available" if value is not None else "no_coverage", "metres": value}
