"""Private fixture server for verify_studio_file_availability.cjs, never deployed.

Byte-presence fixtures are deliberately NOT PDFs or approved project releases.
The real HTTP routes/UI are used; only initial saved state is seeded.
--empty starts a fresh ordinary editor without fixtures or calculation stubs.
"""
import json
import os
from pathlib import Path
import socket
import sys


def main():
    root = Path(sys.argv[1]).resolve()
    if not root.is_dir() or any(root.iterdir()):
        raise ValueError("Expected a fresh empty mkdtemp directory")
    for key, folder in {
        "ZARYA_STUDIO_DIR": "studio", "ZARYA_PROJECTS_DIR": "projects",
        "ZARYA_PASSPORTS_DIR": "passports", "ZARYA_RELEASES_DIR": "releases",
        "ZARYA_PILOT_DIR": "pilot",
    }.items():
        os.environ[key] = str(root / folder)
    os.environ.update(ZARYA_STUDIO_ENABLED="1", ZARYA_PILOT_ENABLED="0",
                      ZARYA_NORMATIVE_MONITOR_ENABLED="0")

    import uvicorn
    from app.main import app
    from app.intake.studio_store import StudioStore
    from app.intake.studio_project import calculate_project, STUDIO_HANDOFF_VERSION
    from app.intake.pilot_objects import calculation_stamp
    from app.pz.water_scheme_delivery import DOCUMENT_RENDER_VERSION
    from app.web import studio, wizard
    from tests.test_studio_apartment_meters import draft as input_fixture

    storage = StudioStore(root / "studio")
    wizard._OUT_ROOT = str(root / "runs")
    manifest = {}
    flags = set(sys.argv[2:])
    if not flags <= {"--empty", "--preview-faults"} or ("--preview-faults" in flags and "--empty" not in flags):
        raise ValueError("Unsupported private smoke server flags")
    empty = "--empty" in flags
    if "--preview-faults" in flags:
        from scripts.studio_preview_faults import install
        install(root)
    for kind in (() if empty else ("preview", "package")):
        did, initial = storage.create()
        data = input_fixture()
        data["project_calculation"] = calculate_project(data)
        identifier = "a" * 32 if kind == "preview" else "b" * 10
        folder = (storage.folder(did) / "previews" / identifier if kind == "preview"
                  else root / "runs" / identifier)
        folder.mkdir(parents=True)
        for name in ("scheme.pdf", "pz.pdf"):
            (folder / name).write_bytes(b"ZARYA UI presence fixture, NOT A PDF: " + name.encode())
        documents = [dict(name="scheme.pdf", label="Схема · тест доступности",
                          kind="wastewater_scheme_pdf", state="preliminary"),
                     dict(name="pz.pdf", label="ПЗ · тест доступности", kind="pz_pdf", state="preliminary")]
        with storage.edit(did, initial["revision"]) as stored:
            stored.update(data)
            stored[kind] = dict(
                state="preview" if kind == "preview" else "ready",
                render_version=DOCUMENT_RENDER_VERSION, handoff_version=STUDIO_HANDOFF_VERSION,
                stamp=calculation_stamp(stored), documents=documents,
            )
            if kind == "preview":
                stored[kind].update(id=identifier, artifact_files={
                    "Принципиальная схема К1/К2": ["scheme.pdf"], "Пояснительная записка": ["pz.pdf"]},
                    artifact_readiness={"Принципиальная схема К1/К2": False})
            else:
                stored[kind]["run_id"] = identifier
                wizard._RUNS[identifier] = dict(outdir=str(folder))
        manifest[kind] = dict(draft_id=did, identifier=identifier, folder=str(folder),
                              draft_file=str(storage.folder(did) / "draft.json"))

    def forbidden(*args, **kwargs):
        raise AssertionError("Read-only browser smoke must not calculate or restore a Project")
    if not empty:
        studio.calculate_project = forbidden
        wizard.design_ios2 = forbidden
        wizard._restore_run = forbidden
    # Bind once to an OS-selected loopback port: never reuse an existing service.
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        manifest["base_url"] = f"http://127.0.0.1:{sock.getsockname()[1]}"
        (root / "fixture.json").write_text(json.dumps(manifest), encoding="utf-8")
        server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
        server.run(sockets=[sock])


if __name__ == "__main__":
    main()
