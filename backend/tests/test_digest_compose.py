"""OAAS O04 — digest compose must pin every service and forbid pulls.

Reads files from the repo root. Under `scripts/check.sh` the backend pytest
container bind-mounts `scripts/` and `deploy/` next to `/app` (see check.sh).
"""

from __future__ import annotations

from pathlib import Path

ROOT_CANDIDATES = (
    Path(__file__).resolve().parents[2],  # host: …/solver
    Path("/repo"),
    Path(__file__).resolve().parents[1].parent,  # /app -> parent if weird
)


def _root() -> Path:
    for candidate in ROOT_CANDIDATES:
        if (candidate / "scripts" / "render-digest-compose.sh").is_file():
            return candidate
        if (candidate / "deploy" / "compose" / "docker-compose.digests.example.yml").is_file():
            return candidate
    # Docker check.sh mounts: /app = backend, /scripts, /deploy
    if Path("/scripts/render-digest-compose.sh").is_file():
        return Path("/")
    raise AssertionError("cannot locate repo root with scripts/render-digest-compose.sh")


def test_example_digest_compose_pins_all_services_with_pull_never():
    root = _root()
    example = root / "deploy" / "compose" / "docker-compose.digests.example.yml"
    if not example.is_file():
        example = Path("/deploy/compose/docker-compose.digests.example.yml")
    text = example.read_text(encoding="utf-8")
    for name in ("postgres", "clickhouse", "backend", "worker", "frontend"):
        assert f"{name}:" in text
    assert text.count("pull_policy: never") >= 5
    assert "@sha256:" in text
    assert "REPLACE_" in text


def test_render_script_documents_offline_up_command():
    root = _root()
    script = root / "scripts" / "render-digest-compose.sh"
    if not script.is_file():
        script = Path("/scripts/render-digest-compose.sh")
    text = script.read_text(encoding="utf-8")
    assert "pull_policy: never" in text
    assert "RepoDigests" in text
    assert "docker-compose.digests.yml" in text
    assert "--no-build" in text


def test_offline_bundle_invokes_digest_render():
    root = _root()
    bundle = root / "scripts" / "offline-bundle.sh"
    if not bundle.is_file():
        bundle = Path("/scripts/offline-bundle.sh")
    text = bundle.read_text(encoding="utf-8")
    assert "render-digest-compose.sh" in text
