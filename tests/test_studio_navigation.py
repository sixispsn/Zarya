"""Home is a destination, not an automatic redirect to a saved draft."""
import os
from pathlib import Path
import shutil
import subprocess

from fastapi.testclient import TestClient
import pytest

from app.intake.project_store import ProjectStore
from app.intake.request_dto import IOS2Request, DocumentRequest
from app.main import app
from app.web import wizard


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ZARYA_STUDIO_ENABLED", "1")
    monkeypatch.setenv("ZARYA_STUDIO_DIR", str(tmp_path / "studio"))
    monkeypatch.setattr(wizard, "_STORE", ProjectStore(str(tmp_path / "projects")))
    with TestClient(app) as client:
        client.headers["X-Zarya-Studio"] = "1"
        yield client


def test_home_and_explicit_resume_have_distinct_initial_screens(client):
    state = client.post('/studio/api/draft').json()
    for url in ('/', '/studio', '/studio?view=garbage'):
        page = client.get(url)
        assert 'data-view="home"' in page.text
        assert 'id="entry" class="entry" aria-labelledby="entry-title">' in page.text
        assert 'id="workspace" class="workspace" hidden' in page.text
        assert 'data-action="resume"' in page.text
        assert 'data-action="handoff"' not in page.text
    page = client.get('/studio?view=project')
    assert 'data-view="project"' in page.text
    assert 'id="entry" class="entry" aria-labelledby="entry-title" hidden>' in page.text
    # A navigation is read-only: no new draft, revision, or YAML handoff.
    assert client.get('/studio/api/draft').json() == state
    assert wizard._STORE.list() == []


def test_library_keeps_browser_draft_private_and_does_not_fork_it(client):
    state = client.post('/studio/api/draft').json()
    state = client.patch('/studio/api/answer', json={
        'revision': state['revision'], 'field': 'object_name',
        'value': 'Новый дом <script>alert(1)</script>',
    }).json()
    library = client.get('/studio/projects')
    assert 'Новый дом &lt;script&gt;' in library.text
    assert '<script>alert(1)' not in library.text
    assert 'href="/studio?view=project"' in library.text
    assert '/static/wizard.js' not in library.text
    assert client.get('/studio/api/draft').json() == state
    client.cookies.clear()
    assert 'Новый дом' not in client.get('/studio/projects').text
    assert wizard._STORE.list() == []


def test_legacy_projects_are_explicit_archive_without_loss(client):
    request = IOS2Request(
        document=DocumentRequest('АРХИВ', 'Прежний дом', 'Москва'),
        building_type='residential', floors=2, building_height_m=6.6,
    )
    pid = wizard._STORE.save(request)
    source = Path(wizard._STORE.root, f'{pid}.yaml').read_bytes()
    before = wizard._STORE.source_sha256(pid)
    library = client.get('/studio/projects')
    assert '<details class="studio-archive">' in library.text
    assert 'Архив прежних проектов' in library.text
    assert f'href="/wizard/open/{pid}" target="_blank"' in library.text
    downloaded = client.get(f'/studio/archive/{pid}/source.yaml')
    assert downloaded.content == source
    assert downloaded.headers['cache-control'] == 'no-store'
    assert wizard._STORE.source_sha256(pid) == before
    assert wizard._STORE.load(pid) == request
    assert client.get('/studio/api/draft').json() == {'draft': None}
    assert client.get('/studio/archive/not-a-project/source.yaml').status_code == 404


def test_frontend_home_does_not_open_saved_project():
    node = os.environ.get('NODE_BINARY') or shutil.which('node')
    assert node, 'Set NODE_BINARY for Studio navigation tests'
    result = subprocess.run([node, '--test', 'tests/studio_navigation.test.cjs'],
                            text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
