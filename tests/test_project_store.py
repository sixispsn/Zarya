# -*- coding: utf-8 -*-
"""Тесты app/intake/project_store.py + prefill формы Wizard."""
import pytest

from app.intake.project_store import ProjectStore
from app.intake.yaml_io import load_request

YAML = """
document: {cipher: Т-ИОС2, object_name: Объект, organization: Орг}
building: {type: residential, floors: 16, height_m: 48}
fire: {streams: 2}
rooms: [{name: Коридор, length_m: 42, width_m: 2.4, height_m: 3.0}]
network:
  source: {node: К1, kind: city_main, available_head_m: 32}
  runs: [{from: К1, to: К2, length_m: 36}, {from: К2, to: К1, length_m: 36}]
  risers: [{name: СТ-1, at: К1, height_m: 46.5, cabinet_elevation_m: 45.6}]
"""


@pytest.fixture
def store(tmp_path):
    return ProjectStore(root=str(tmp_path))


def _req():
    return load_request(YAML)


def test_save_and_load(store):
    pid = store.save(_req())
    assert store.exists(pid)
    assert store.load(pid) == _req()


def test_list_sorted_and_titled(store):
    store.save(_req())
    lst = store.list()
    assert len(lst) == 1
    assert lst[0].title == "Объект"


def test_update_same_id(store):
    pid = store.save(_req())
    req = _req()
    req.floors = 20
    assert store.save(req, project_id=pid) == pid
    assert store.load(pid).floors == 20


def test_delete(store):
    pid = store.save(_req())
    store.delete(pid)
    assert not store.exists(pid)
    assert store.list() == []


def test_load_missing_raises(store):
    with pytest.raises(FileNotFoundError):
        store.load("aaaaaaaaaa")


def test_bad_id_rejected(store):
    # защита от traversal: только hex-id
    with pytest.raises(ValueError):
        store.load("../../etc/passwd")
    assert store.exists("../oops") is False


def test_yaml_on_disk_is_readable(store, tmp_path):
    pid = store.save(_req())
    raw = open(tmp_path / f"{pid}.yaml", encoding="utf-8").read()
    assert "cipher: Т-ИОС2" in raw   # человекочитаемый YAML, не бинарь


# ── prefill формы ────────────────────────────────────────────────────────────

def test_form_prefill_renders_saved_values():
    from jinja2 import Environment, FileSystemLoader
    env = Environment(loader=FileSystemLoader("app/web/templates"))
    h = env.get_template("wizard_form.html").render(
        errors=[], prefill=_req(), project_id="ab12cd34ef")
    assert "Т-ИОС2" in h
    assert 'name="project_id" value="ab12cd34ef"' in h
    assert "2026-089" not in h        # демо не просачивается


def test_form_without_prefill_uses_demo():
    from jinja2 import Environment, FileSystemLoader
    env = Environment(loader=FileSystemLoader("app/web/templates"))
    h = env.get_template("wizard_form.html").render(errors=[], prefill=None,
                                                    project_id=None)
    assert "2026-089-ИОС2" in h       # демо-заполнение живо
    assert "DEMO-ТУ-01" in h
    assert "РС-1" in h
    assert 'name="consumer_count"' in h


def test_projects_page_template():
    from jinja2 import Environment, FileSystemLoader
    from app.intake.project_store import ProjectSummary
    env = Environment(loader=FileSystemLoader("app/web/templates"))
    h = env.get_template("wizard_projects.html").render(
        projects=[ProjectSummary("ab12cd34ef", "Тестовый дом", "2026-07-12T10:00:00")])
    assert "Тестовый дом" in h
    assert "/wizard/open/ab12cd34ef" in h


def test_wizard_new_routes_registered():
    from app.main import app
    paths = app.openapi()["paths"].keys()
    assert "/wizard/projects" in paths
    assert "/wizard/open/{project_id}" in paths
