"""Main entry, shared navigation and deployment persistence contracts."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.web import wizard
from app.intake.project_store import ProjectStore
from app.intake.request_dto import IOS2Request, DocumentRequest


def test_main_defaults_to_white_workspace(monkeypatch):
    monkeypatch.delenv("ZARYA_STUDIO_ENABLED", raising=False)
    with TestClient(app) as client:
        response = client.get("/")
        assert response.url.path == "/studio"
        assert response.status_code == 200
        assert 'data-ui="white"' in response.text
        assert "тестовый режим" not in response.text
        assert "Добавьте исходные документы" in response.text


@pytest.mark.parametrize("url", [
    "/studio", "/studio/projects", "/wizard", "/wizard/projects", "/wizard/building-model",
    "/wizard/architecture", "/wizard/analyze", "/wizard/normatives",
])
def test_main_pages_have_one_shared_navigation(url, monkeypatch, tmp_path):
    monkeypatch.setenv("ZARYA_STUDIO_ENABLED", "1")
    monkeypatch.setenv("ZARYA_NORMATIVE_RADAR_DIR", str(tmp_path / "radar"))
    with TestClient(app) as client:
        response = client.get(url)
    assert response.status_code == 200
    assert response.text.count('class="site-header"') == 1
    assert 'id="main-content"' in response.text
    assert 'data-theme="light" data-ui="white"' in response.text
    assert '/static/site.css' in response.text
    assert 'class="topnav"' not in response.text
    assert 'localStorage.getItem("zarya-theme")' not in response.text
    header = response.text.split('<header class="site-header">')[1].split('</header>')[0]
    for link in ("/studio", "/studio?view=project", "/studio/projects", "/wizard/normatives"):
        assert f'href="{link}"' in header
    for link in ("/wizard", "/wizard/projects", "/wizard/building-model",
                 "/wizard/architecture", "/wizard/analyze"):
        assert f'href="{link}"' not in header
    assert 'data-studio-handoff' not in header
    assert '<span class="brand-version">альфа 0.02</span>' in header


def test_alpha_version_uses_one_label_in_header_and_home_logo():
    templates = Path('app/web/templates')
    assert (templates / 'site_version.html').read_text().strip() == '<span class="brand-version">альфа 0.02</span>'
    for name in ('studio.html', 'site_header.html'):
        assert "{% include 'site_version.html' %}" in (templates / name).read_text()
    # UI maturity is not stamped onto generated engineering documents.
    assert not any('site_version.html' in file.read_text()
                   for file in Path('app/pz/templates').glob('*.html'))


def test_existing_projects_stay_editable_and_titles_are_escaped(tmp_path, monkeypatch):
    store = ProjectStore(str(tmp_path / "projects"))
    monkeypatch.setattr(wizard, "_STORE", store)
    title = "Дом <script>alert('x')</script>"
    request = IOS2Request(
        document=DocumentRequest("ТЕСТ", title, "Москва"),
        building_type="residential", floors=2, building_height_m=6.6,
    )
    pid = store.save(request)
    with TestClient(app) as client:
        library = client.get("/wizard/projects")
        assert f'href="/wizard/open/{pid}"' in library.text
        assert "<script>alert(" not in library.text
        assert 'onsubmit="return confirm' not in library.text
        assert 'data-library-current' in library.text
        project = client.get(f"/wizard/open/{pid}")
        assert project.status_code == 200
        assert f'name="project_id" value="{pid}"' in project.text
    assert store.load(pid) == request


def test_studio_persistence_and_single_personal_login_boundary():
    compose = Path("compose.yaml").read_text()
    assert "ZARYA_STUDIO_DIR: /data/projects/_studio" in compose
    assert "ZARYA_STUDIO_ENABLED: ${ZARYA_STUDIO_ENABLED:-1}" in compose
    caddy = Path("deploy/Caddyfile").read_text()
    # User approved removing only the outer shared password on 28.09.2026.
    # A default fresh compose launch MUST stay closed until personal auth is on.
    assert "basic_auth {" not in caddy
    assert 'ZARYA_REQUIRE_PILOT: "1"' in compose
    assert "ZARYA_REQUIRE_PILOT" in Path("app/web/pilot.py").read_text()
