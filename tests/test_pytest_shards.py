"""CI partition/evidence checks: no engineering values or goldens involved."""

import json
from xml.etree import ElementTree as ET

import pytest

from scripts.pytest_progress import pytest_runtest_logfinish, pytest_runtest_logstart
from scripts.pytest_shards import PRIVATE_SOURCE_TESTS, check, collection_ids, junit_key, partition


IDS = [f"tests/test_{module}.py::test_{case}" for module in "abcdefgh" for case in range(3)]


def test_partition_keeps_modules_whole_and_covers_every_collected_node_once():
    selected = []
    for index in range(4):
        modules, manifest = partition(IDS, index, 4)
        assert len(modules) == 2
        assert all(sum(n.startswith(m + "::") for n in manifest["selected"]) == 3 for m in modules)
        selected.extend(manifest["selected"])
    assert sorted(selected) == sorted(IDS)
    assert len(selected) == len(set(selected))


@pytest.mark.parametrize("index,total", [(-1, 4), (4, 4), (0, 0), (0, -1), (8, 9)])
def test_invalid_or_empty_partition_fails(index, total):
    with pytest.raises(ValueError):
        partition(IDS, index, total)


def test_collection_uses_pytest_node_ids_and_checks_its_declared_count():
    output = "\n".join(IDS) + "\nwarning text\n24 tests collected in 1.0s\n"
    assert collection_ids(output) == sorted(IDS)
    for broken in (output.replace("24 tests", "25 tests"), output + IDS[0], "no tests collected"):
        with pytest.raises(ValueError):
            collection_ids(broken)


def test_junit_class_and_parameter_identity_matches_pytest():
    assert junit_key("tests/test_x.py::TestC::test_y[ip::1]") == ("tests.test_x.TestC", "test_y[ip::1]")


def evidence(directory, ids=IDS):
    for index in range(4):
        _, manifest = partition(ids, index, 4)
        (directory / f"shard-{index}.json").write_text(json.dumps(manifest))
        root = ET.Element("testsuites")
        suite = ET.SubElement(root, "testsuite", tests=str(len(manifest["selected"])), failures="0", errors="0", skipped="0")
        for node in manifest["selected"]:
            classname, name = junit_key(node)
            ET.SubElement(suite, "testcase", classname=classname, name=name)
        ET.ElementTree(root).write(directory / f"shard-{index}.xml")


def test_complete_protocol_is_accepted(tmp_path):
    evidence(tmp_path)
    assert check(tmp_path, 4) == (24, 0)


@pytest.mark.parametrize("mutation", ["failure", "error", "missing_case", "unexpected_skip", "counter_lie", "wrong_case"])
def test_bad_junit_never_confirms_full_suite(tmp_path, mutation):
    evidence(tmp_path)
    path = tmp_path / "shard-0.xml"
    tree = ET.parse(path)
    suite = tree.getroot()[0]
    if mutation in ("failure", "error"):
        ET.SubElement(suite[0], mutation)
    elif mutation == "missing_case":
        suite.remove(suite[0])
    elif mutation == "unexpected_skip":
        ET.SubElement(suite[0], "skipped")
        suite.set("skipped", "1")
    elif mutation == "wrong_case":
        suite[0].set("name", "test_not_executed")
    else:
        suite.set("tests", "7")
    tree.write(path)
    with pytest.raises(ValueError):
        check(tmp_path, 4)


def test_only_named_private_source_checks_can_be_skipped(tmp_path):
    ids = IDS + [classname.replace(".", "/") + ".py::" + name for classname, name in PRIVATE_SOURCE_TESTS]
    evidence(tmp_path, ids)
    for path in tmp_path.glob("shard-*.xml"):
        tree = ET.parse(path)
        suite = tree.getroot()[0]
        skipped = 0
        for case in suite:
            if (case.get("classname"), case.get("name")) in PRIVATE_SOURCE_TESTS:
                ET.SubElement(case, "skipped")
                skipped += 1
        suite.set("skipped", str(skipped))
        tree.write(path)
    assert check(tmp_path, 4) == (27, 3)


@pytest.mark.parametrize("mutation", ["missing", "duplicate_index", "duplicate_nodes", "digest", "count"])
def test_bad_partition_evidence_is_rejected(tmp_path, mutation):
    evidence(tmp_path)
    path = tmp_path / "shard-0.json"
    data = json.loads(path.read_text())
    if mutation == "missing":
        path.unlink()
    else:
        if mutation == "duplicate_index":
            data["index"] = 1
        elif mutation == "duplicate_nodes":
            data["selected"][0] = data["selected"][1]
        elif mutation == "digest":
            data["collection_sha256"] = "wrong"
        else:
            data["collection_count"] += 1
        path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        check(tmp_path, 4)


def test_progress_records_start_and_finish_without_changing_tests(tmp_path, monkeypatch):
    path = tmp_path / "progress.jsonl"
    monkeypatch.setenv("ZARYA_PYTEST_PROGRESS", str(path))
    pytest_runtest_logstart(IDS[0], None)
    pytest_runtest_logfinish(IDS[0], None)
    assert [json.loads(line) for line in path.read_text().splitlines()] == [
        {"event": "start", "nodeid": IDS[0]}, {"event": "finish", "nodeid": IDS[0]},
    ]
    monkeypatch.delenv("ZARYA_PYTEST_PROGRESS")
    pytest_runtest_logstart(IDS[1], None)
    assert len(path.read_text().splitlines()) == 2
