from pathlib import Path


def test_docker_image_embeds_explicit_build_commit():
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    assert "ARG ZARYA_BUILD_COMMIT=unknown" in dockerfile
    assert "ZARYA_BUILD_COMMIT=${ZARYA_BUILD_COMMIT}" in dockerfile


def test_compose_persists_releases_and_passes_build_commit():
    compose = Path("compose.yaml").read_text(encoding="utf-8")
    assert "ZARYA_RELEASES_DIR: /data/projects/_releases" in compose
    assert "ZARYA_BUILD_COMMIT: ${ZARYA_BUILD_COMMIT:-unknown}" in compose


def test_ci_has_parity_full_suite_and_container_smoke_gates():
    workflow = Path(".github/workflows/quality.yml").read_text(encoding="utf-8")
    assert "Legacy parity gate" in workflow
    assert "Full test suite" in workflow
    assert "container-smoke" in workflow
    assert "github.sha" in workflow
