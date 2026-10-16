from pathlib import Path


def test_single_login_release_is_fail_closed_and_rolls_back_proxy_separately():
    dockerfile = Path("deploy/admin-release.Dockerfile").read_text()
    assert "FROM zarya-release:20260928-pilot-attachments" in dockerfile
    assert "/app/.require-personal-auth" in dockerfile
    assert all(excluded not in dockerfile for excluded in ("app/calc", "app/pz", "legacy/"))
    assert 'ZARYA_REQUIRE_PILOT: "1"' in Path("deploy/admin-release.override.yaml").read_text()
    activation = Path("deploy/activate-admin.sh").read_text()
    assert "verify_backup_restore.py" in activation and "Caddyfile.before" in activation
    switch = Path("deploy/enable-single-login.sh").read_text()
    assert "caddy validate" in switch and "caddy reload" in switch and "Caddyfile.before" in switch
    assert "basic_auth" not in Path("deploy/Caddyfile").read_text()


def test_snapshot_permissions_and_nonroot_import_are_checked_during_build():
    dockerfile = Path("Dockerfile").read_text()
    assert "chmod -R a+rX /app/app /app/demo /app/legacy /app/scripts" in dockerfile
    assert dockerfile.index("USER zarya") < dockerfile.index("from app.main import app; assert app")


def test_docker_image_embeds_explicit_build_commit():
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    assert "ARG ZARYA_BUILD_COMMIT=unknown" in dockerfile
    assert "ZARYA_BUILD_COMMIT=${ZARYA_BUILD_COMMIT}" in dockerfile


def test_study_export_has_executable_legacy_reference_in_image():
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    ignore = Path(".dockerignore").read_text(encoding="utf-8")
    assert "nodejs" in dockerfile
    for source in ("legacy/sp30_calculator.html", "scripts/legacy_rainwater_reference.mjs"):
        assert f"COPY {source} ./" in dockerfile
        assert f"!{source}" in ignore


def test_compose_persists_releases_and_passes_build_commit():
    compose = Path("compose.yaml").read_text(encoding="utf-8")
    assert "ZARYA_RELEASES_DIR: /data/projects/_releases" in compose
    assert "ZARYA_BUILD_COMMIT: ${ZARYA_BUILD_COMMIT:-unknown}" in compose
    assert "ZARYA_HARD_QUALITY_GATES: ${ZARYA_HARD_QUALITY_GATES:-0}" in compose


def test_pilot_cli_is_shipped_and_identity_store_is_persistent():
    assert "COPY scripts/pilot_access.py ./scripts/pilot_access.py" in Path("Dockerfile").read_text()
    assert "!scripts/pilot_access.py" in Path(".dockerignore").read_text()
    compose = Path("compose.yaml").read_text()
    assert "ZARYA_PILOT_DIR: /data/projects/_pilot" in compose
    assert "ZARYA_PILOT_ENABLED: ${ZARYA_PILOT_ENABLED:-0}" in compose
    ignore = Path(".dockerignore").read_text().splitlines()
    assert all(path in ignore for path in ("private", "backup", "restored-*", "*.tar.gz"))


def test_ci_has_parity_full_suite_and_container_smoke_gates():
    workflow = Path(".github/workflows/quality.yml").read_text(encoding="utf-8")
    assert "Legacy parity gate" in workflow
    assert "Full test suite" in workflow
    assert "container-smoke" in workflow
    assert "github.sha" in workflow
    assert "Normative contract gate" in workflow
    assert "Critical-module coverage gate" in workflow
    assert "--cov=app/ --cov-config=coverage-critical.ini" in workflow
    coverage = Path("coverage-critical.ini").read_text()
    assert all(path in coverage for path in (
        "app/quality_gates.py", "app/architecture/catalog.py",
        "app/architecture/engineering_handoff.py", "app/architecture/program_report.py",
        "app/architecture/program_store.py", "app/architecture/residential_program.py",
        "app/intake/questions.py", "app/intake/preflight.py",
    ))
    assert "--cov-fail-under=70" in workflow
    assert "node --test tests/*.test.cjs" in workflow
    assert "Working legacy is reproducible" in workflow
    assert "127.0.0.1:18000:8000" in workflow
    assert "Approved visual regression gate" in workflow
    assert "Build known-incomplete control case" in workflow
    assert "negative regression, not release approval" in workflow
    assert "--expected-blockers demo/control_blockers.json" in workflow
    # Do not turn typed FastAPI decorators into Any by skipping imports.
    assert "--follow-imports=silent" in workflow
    assert "--follow-imports=skip" not in workflow
    assert "scripts/verify_control_release.py" in workflow
    assert "app/architecture" in workflow
    assert "app/web/building_model.py" in workflow
    assert "tests/test_building_program.py" in workflow
    assert "tests/test_building_program_handoff.py" in workflow
    assert "tests/test_building_program_report.py" in workflow
    assert "tests/test_building_model_web.py" in workflow
    assert "/wizard/building-model" in workflow


def test_feedback_release_keeps_personal_auth_and_does_not_replace_core():
    override = Path("deploy/feedback-release.override.yaml").read_text()
    assert 'ZARYA_PILOT_ENABLED: "1"' in override
    assert "ZARYA_PILOT_INSECURE_LOCAL" not in override
    dockerfile = Path("deploy/feedback-release.Dockerfile").read_text()
    assert "FROM zarya-release:20260927-pilot-access" in dockerfile
    for excluded in ("app/calc", "app/pz", "legacy/"):
        assert excluded not in dockerfile
    activation = Path("deploy/activate-feedback.sh").read_text()
    assert "verify_backup_restore.py" in activation
    assert "--no-deps --no-build --wait" in activation


def test_configurator_release_preserves_core_private_login_and_backup():
    override = Path("deploy/configurator-release.override.yaml").read_text()
    assert 'ZARYA_PILOT_ENABLED: "1"' in override
    assert "ZARYA_PILOT_INSECURE_LOCAL" not in override
    dockerfile = Path("deploy/configurator-release.Dockerfile").read_text()
    assert "FROM zarya-release:20260927-pilot-feedback" in dockerfile
    assert "studio_configurator.js" in dockerfile
    assert all(excluded not in dockerfile for excluded in ("app/calc", "app/pz", "legacy/"))
    activation = Path("deploy/activate-configurator.sh").read_text()
    assert "verify_backup_restore.py" in activation and "restored-pre-configurator" in activation
    assert "--no-deps --no-build --wait" in activation


def test_objects_release_preserves_core_auth_and_verified_backup():
    override = Path("deploy/objects-release.override.yaml").read_text()
    assert 'ZARYA_PILOT_ENABLED: "1"' in override
    assert "ZARYA_PILOT_INSECURE_LOCAL" not in override
    dockerfile = Path("deploy/objects-release.Dockerfile").read_text()
    assert "FROM zarya-release:20260928-studio-configurator" in dockerfile
    assert all(excluded not in dockerfile for excluded in ("app/calc", "app/pz", "legacy/"))
    activation = Path("deploy/activate-objects.sh").read_text()
    assert "verify_backup_restore.py" in activation and "restored-pre-objects" in activation
    assert "--no-deps --no-build --wait" in activation


def test_attachments_release_preserves_core_auth_and_verified_backup():
    override = Path("deploy/attachments-release.override.yaml").read_text()
    assert 'ZARYA_PILOT_ENABLED: "1"' in override and "ZARYA_PILOT_INSECURE_LOCAL" not in override
    dockerfile = Path("deploy/attachments-release.Dockerfile").read_text()
    assert "FROM zarya-release:20260928-pilot-objects" in dockerfile
    assert "pilot_pdf_probe.py" in dockerfile
    assert all(excluded not in dockerfile for excluded in ("app/calc", "app/pz", "legacy/"))
    activation = Path("deploy/activate-attachments.sh").read_text()
    assert "verify_backup_restore.py" in activation and "restored-pre-attachments" in activation
    assert "--no-deps --no-build --wait" in activation
