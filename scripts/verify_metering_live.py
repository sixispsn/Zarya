"""Read-only HTTPS release check; logs into a separate owner session, then revokes it."""
import os
from pathlib import Path
import re

import httpx


def main():
    keys = re.findall(r"zarya_[A-Za-z0-9_-]{43}", Path(os.environ["ZARYA_OWNER_KEY_FILE"]).read_text())
    assert len(set(keys)) == 1, "Unrecognized key file"
    base = "https://zaryaproekt.ru"
    with httpx.Client(base_url=base, timeout=60, headers={"Origin": base, "X-Zarya-Access": "1"}) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/studio/api/draft").status_code == 401
        r = client.post("/access/login", json={"key": keys[0], "remember_device": True})
        assert r.status_code == 200, "Owner login failed"
        cookie = r.headers.get("set-cookie", "")
        assert all(s in cookie for s in ("Secure", "HttpOnly", "SameSite=strict", "Max-Age="))
        try:
            before = client.get("/studio/api/draft").json()
            page = client.get("/studio?view=project")
            assert page.status_code == 200
            assert "/static/studio.js?v=25" in page.text
            assert "/static/studio.css?v=18" in page.text
            assert "/static/studio_configurator.js?v=2" in page.text
            js = client.get("/static/studio_configurator.js?v=2")
            assert js.status_code == 200 and "Водомерный узел" in js.text
            assert "vu_technology" in js.text and "vu_telemetry" in js.text
            assert "metering-options" in client.get("/static/studio.css?v=18").text
            assert client.get("/access/admin").status_code == 200
            assert client.get("/studio/api/location/config").status_code == 200
            fields = {f["key"] for f in before["fields"]}
            assert {"vu_technology", "vu_telemetry", "vu_magnetic_filter"} <= fields
            assert client.get("/studio/api/draft").json() == before
            assert client.post("/studio/api/draft", headers={"Origin": "https://invalid.example"}).status_code == 403
        finally:
            assert client.post("/access/logout").status_code == 303
        assert client.get("/studio/api/draft").status_code == 401
    print("PASS: production HTTPS, remembered private login, new UI/options, admin/map, unchanged draft, CSRF and logout.")


if __name__ == "__main__":
    main()
