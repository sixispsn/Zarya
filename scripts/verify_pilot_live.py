"""Read-only HTTP verification of the actual owner account, except login/logout.

Run inside the production app with the key on stdin; never prints credentials,
project contents or cookies. Does not create/claim/modify engineering drafts.
"""
import json
import sys

import httpx


def main():
    key = sys.stdin.read().strip()
    if not key.startswith("zarya_") or len(key) != 49:
        raise SystemExit("Invalid private key input")
    # Equivalent to the internal Caddy -> Uvicorn hop. HTTPS is asserted by the
    # trusted proxy header, not by disabling the application's secure-cookie rule.
    headers = {"Host": "zaryaproekt.ru", "X-Forwarded-Proto": "https",
               "Origin": "https://zaryaproekt.ru", "X-Zarya-Access": "1"}
    with httpx.Client(base_url="http://127.0.0.1:8000", headers=headers, timeout=30) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/studio/api/draft").status_code == 401
        page = client.get("/access/login")
        assert page.status_code == 200 and "Персональный ключ" in page.text
        response = client.post("/access/login", json={"key": key})
        assert response.status_code == 200
        session = response.cookies.get("zarya_pilot_session")
        assert session and "Secure" in response.headers["set-cookie"]
        assert "HttpOnly" in response.headers["set-cookie"] and "SameSite=strict" in response.headers["set-cookie"]
        # httpx correctly doesn't send a Secure cookie over this internal HTTP
        # test hop. Send it explicitly, solely to loopback, then revoke it.
        client.headers["Cookie"] = "zarya_pilot_session=" + session
        try:
            workspace = client.get("/studio")
            assert workspace.status_code == 200
            assert 'data-feedback-open' in workspace.text
            assert 'id="delete-document-dialog"' in workspace.text
            assert client.get("/access/feedback").status_code == 200
            assert client.get("/access/admin").status_code == 200
            assert client.get("/studio/projects").status_code == 200
            assert 'data-action="pilot-snapshot"' in workspace.text
            assert client.get("/studio/pilot-objects").status_code == 200
            assert client.get("/static/pilot_attachments.js?v=1").status_code == 200
            assert client.get("/wizard/projects").status_code == 200
            assert client.get("/studio/api/draft").status_code == 200
            assert client.post("/studio/api/draft", headers={"Origin": "https://invalid.example"}).status_code == 403
        finally:
            assert client.post("/access/logout").status_code == 303
        assert client.get("/studio/api/draft").status_code == 401
    print(json.dumps({"owner_login": "passed", "secure_cookie": True,
                      "owner_archive": "accessible", "feedback_inbox": "accessible", "draft": "read_only",
                      "cross_site_mutation": "blocked", "logout": "revoked",
                      "admin": "accessible", "transport": "trusted internal proxy hop; external gate checked separately"}))


if __name__ == "__main__":
    main()
