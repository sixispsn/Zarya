"""Optional CI-only progress evidence, including the active test on timeout."""

import json
import os
from pathlib import Path


def record(event, nodeid):
    target = os.environ.get("ZARYA_PYTEST_PROGRESS")
    if target:
        with Path(target).open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"event": event, "nodeid": nodeid}) + "\n")


def pytest_runtest_logstart(nodeid, location):
    record("start", nodeid)


def pytest_runtest_logfinish(nodeid, location):
    record("finish", nodeid)
