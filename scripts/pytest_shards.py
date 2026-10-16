"""Run every collected pytest module once; verify the combined CI evidence."""

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from xml.etree import ElementTree as ET


PRIVATE_SOURCE_TESTS = {
    ("tests.test_fire_pump_envelope", "test_source_hashes_when_user_catalogs_available"),
    ("tests.test_fire_station_documents", "test_private_station_sources_match_recorded_hashes_when_available"),
    ("tests.test_fire_diaphragm_graph", "test_samara_apertures_pdf_with_verified_private_nomogram"),
}


def collection_ids(output):
    ids = [line for line in output.splitlines() if line.startswith("tests/") and "::" in line]
    counts = re.findall(r"^(\d+) tests? collected\b", output, re.M)
    if len(counts) != 1 or int(counts[0]) != len(ids) or not ids or len(set(ids)) != len(ids):
        raise ValueError("Incomplete or ambiguous pytest collection")
    return sorted(ids)


def identity(ids):
    return hashlib.sha256(json.dumps(sorted(ids), ensure_ascii=True).encode()).hexdigest()


def junit_key(nodeid):
    # Match pytest's xunit2 address representation; :: inside [parameter IDs]
    # belongs to the test name, not to a class hierarchy.
    address, bracket, parameters = nodeid.partition("[")
    names = address.split("::")
    names[0] = re.sub(r"\.py$", "", names[0].replace("/", "."))
    names[-1] += bracket + parameters
    return ".".join(names[:-1]), names[-1]


def partition(ids, index, total):
    if total < 1 or not 0 <= index < total:
        raise ValueError("Invalid shard index/count")
    modules = sorted({node.split("::", 1)[0] for node in ids})
    chosen = modules[index::total]
    if not chosen:
        raise ValueError("Empty shard")
    selected = [node for node in ids if node.split("::", 1)[0] in chosen]
    return chosen, {
        "index": index, "total": total, "collection_count": len(ids),
        "collection_sha256": identity(ids), "selected": selected,
    }


def run(index, total, directory):
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "--color=no"],
        text=True, capture_output=True,
    )
    if result.returncode:
        print(result.stdout, result.stderr)
        return result.returncode
    ids = collection_ids(result.stdout)
    modules, manifest = partition(ids, index, total)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"shard-{index}.json").write_text(json.dumps(manifest), encoding="utf-8")
    env = dict(os.environ, ZARYA_PYTEST_PROGRESS=str(directory / f"shard-{index}-progress.jsonl"))
    print(f"Full collection: {len(ids)}; shard {index}/{total}: {len(manifest['selected'])} tests", flush=True)
    return subprocess.call([
        sys.executable, "-m", "pytest", "-q", "-p", "scripts.pytest_progress",
        f"--junitxml={directory / f'shard-{index}.xml'}", "--durations=20", *modules,
    ], env=env)


def check(directory, total):
    manifests = [json.loads(p.read_text()) for p in directory.glob("shard-*.json")]
    if len(manifests) != total or {m["index"] for m in manifests} != set(range(total)):
        raise ValueError("Missing or duplicate shard")
    signatures = {(m["total"], m["collection_count"], m["collection_sha256"]) for m in manifests}
    if len(signatures) != 1:
        raise ValueError("Shards did not collect the same suite")
    declared_total, count, digest = signatures.pop()
    ids = [node for m in manifests for node in m["selected"]]
    if declared_total != total or len(ids) != count or len(set(ids)) != count or identity(ids) != digest:
        raise ValueError("Missing, duplicated or substituted collected test")
    if len(list(directory.glob("shard-*.xml"))) != total:
        raise ValueError("Missing or extra JUnit shard")
    skipped = 0
    for m in manifests:
        root = ET.parse(directory / f"shard-{m['index']}.xml").getroot()
        suites = list(root)
        if root.tag != "testsuites" or len(suites) != 1 or suites[0].tag != "testsuite":
            raise ValueError("Unexpected JUnit structure")
        suite = suites[0]
        cases = list(suite.iter("testcase"))
        if Counter((c.get("classname"), c.get("name")) for c in cases) != Counter(map(junit_key, m["selected"])):
            raise ValueError("Executed test identities do not match the selected shard")
        if (int(suite.get("tests")) != len(m["selected"]) or len(cases) != len(m["selected"])
                or int(suite.get("failures")) or int(suite.get("errors"))):
            raise ValueError("Failed or incomplete shard")
        actual_skipped = 0
        for case in cases:
            if case.find("failure") is not None or case.find("error") is not None:
                raise ValueError("Failure in JUnit testcase")
            if case.find("skipped") is not None:
                actual_skipped += 1
                if (case.get("classname"), case.get("name")) not in PRIVATE_SOURCE_TESTS:
                    raise ValueError("Unexpected skipped test")
        if int(suite.get("skipped")) != actual_skipped:
            raise ValueError("Inconsistent skipped count")
        skipped += actual_skipped
    print(f"Complete suite: {count - skipped} passed, {skipped} private-source skips; {total} shards")
    return count, skipped


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("run", "check"))
    parser.add_argument("--index", type=int)
    parser.add_argument("--total", type=int, required=True)
    parser.add_argument("--directory", type=Path, default=Path("ci-artifacts/pytest-shards"))
    args = parser.parse_args()
    if args.mode == "check":
        check(args.directory, args.total)
        return 0
    if args.index is None:
        parser.error("run requires --index")
    return run(args.index, args.total, args.directory)


if __name__ == "__main__":
    raise SystemExit(main())
