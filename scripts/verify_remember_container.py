"""Only disposable auth storage; never print secrets or alter real users."""
import os
import time
from unittest.mock import patch

import httpx

from app.intake.pilot_access import AccessStore, REMEMBER_SECONDS


def main():
    assert os.environ.get("ZARYA_DEPLOY_SMOKE") == "1"
    assert os.environ.get("ZARYA_PILOT_DIR") == "/tmp/zarya-smoke/projects/_pilot"
    base = "http://127.0.0.1:8000"
    deadline = time.monotonic()+30
    while time.monotonic() < deadline:
        try:
            if httpx.get(base+"/health", timeout=2).status_code == 200:
                break
        except httpx.HTTPError:
            pass
        time.sleep(.2)
    access = AccessStore()
    uid, key = access.issue("Remember smoke", days=90)
    with httpx.Client(base_url=base, timeout=20, headers={"Origin":base,"X-Zarya-Access":"1"}) as client:
        assert client.get("/studio/api/draft").status_code == 401
        assert 'id="pilot-remember"' in client.get("/access/login").text
        login = client.post("/access/login",json={"key":key,"remember_device":True})
        assert login.status_code == 200
        token = login.cookies.get("zarya_pilot_session")
        assert REMEMBER_SECONDS-5 <= access.cookie_max_age(token) <= REMEMBER_SECONDS
        now = time.time()
        for days in (1,8,29):
            with patch("app.intake.pilot_access.time.time", return_value=now+days*86400):
                assert AccessStore().authenticate(token)
        with patch("app.intake.pilot_access.time.time", return_value=now+30*86400+1):
            assert access.authenticate(token) is None
        assert client.get("/studio").status_code == 200
        assert client.post("/access/logout").status_code == 303
        assert access.authenticate(token) is None
        login = client.post("/access/login",json={"key":key,"remember_device":False})
        assert login.status_code == 200
        cookie = next(h for h in login.headers.get_list("set-cookie") if h.startswith("zarya_pilot_session="))
        assert "Max-Age" not in cookie
        access.revoke(uid)
        assert client.get("/studio").status_code == 401
    print("PASS: remembered 1/8/29 days, hard 30-day cap, persistent cookie, short option, logout and revoke; anonymous denied.")


if __name__ == "__main__":
    main()
