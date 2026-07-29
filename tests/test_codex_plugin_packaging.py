from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_NAME = "tochi-satei-kun"
PLUGIN_ROOT = ROOT / "plugins" / PLUGIN_NAME
MANIFEST_PATH = PLUGIN_ROOT / ".codex-plugin" / "plugin.json"
MARKETPLACE_PATH = ROOT / ".agents" / "plugins" / "marketplace.json"
CANONICAL_SKILL = ROOT / "skills" / PLUGIN_NAME
PACKAGED_SKILL = PLUGIN_ROOT / "skills" / PLUGIN_NAME


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def included_files(root: Path) -> set[Path]:
    ignored_names = {"__pycache__", ".DS_Store", ".pytest_cache", "output", "tests", "PR_HANDOFF.md"}
    ignored_suffixes = {".pyc", ".pyo"}
    return {
        path.relative_to(root)
        for path in root.rglob("*")
        if path.is_file()
        and not any(part in ignored_names for part in path.relative_to(root).parts)
        and path.suffix not in ignored_suffixes
    }


def test_manifest_is_valid_and_matches_folder_name() -> None:
    manifest = load_json(MANIFEST_PATH)
    assert manifest["name"] == PLUGIN_ROOT.name
    assert manifest["version"] == "1.4.3"
    assert manifest["description"]
    assert manifest["author"]["name"]
    assert manifest["repository"] == "https://github.com/signal-yield/tochi-satei-kun"
    assert manifest["license"] == "Apache-2.0"
    assert manifest["skills"] == "./skills/"


def test_marketplace_links_to_plugin() -> None:
    catalog = load_json(MARKETPLACE_PATH)
    assert catalog["name"] == "signal-yield"
    assert catalog["interface"]["displayName"] == "Signal Yield Advisory"
    assert catalog["plugins"] == [
        {
            "name": PLUGIN_NAME,
            "source": {"source": "local", "path": f"./plugins/{PLUGIN_NAME}"},
            "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
            "category": "Productivity",
        }
    ]
    plugin_path = (MARKETPLACE_PATH.parents[2] / catalog["plugins"][0]["source"]["path"]).resolve()
    assert plugin_path == PLUGIN_ROOT.resolve()
    assert plugin_path.is_dir()


def test_plugin_links_to_packaged_skill() -> None:
    manifest = load_json(MANIFEST_PATH)
    skills_root = (PLUGIN_ROOT / manifest["skills"]).resolve()
    assert skills_root.is_dir()
    assert (skills_root / PLUGIN_NAME / "SKILL.md").is_file()


def test_packaged_skill_matches_canonical_skill() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/sync_codex_plugin_skill.py", "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert included_files(CANONICAL_SKILL) == included_files(PACKAGED_SKILL)
    for rel_path in included_files(CANONICAL_SKILL):
        assert (CANONICAL_SKILL / rel_path).read_bytes() == (PACKAGED_SKILL / rel_path).read_bytes()


def test_sync_check_fails_for_deliberate_mismatch(tmp_path: Path) -> None:
    temporary_root = tmp_path / "repo"
    source = temporary_root / "skills" / PLUGIN_NAME
    destination = temporary_root / "plugins" / PLUGIN_NAME / "skills" / PLUGIN_NAME
    scripts = temporary_root / "scripts"
    source.mkdir(parents=True)
    destination.mkdir(parents=True)
    scripts.mkdir()
    (source / "SKILL.md").write_text("canonical\n", encoding="utf-8")
    (destination / "SKILL.md").write_text("stale\n", encoding="utf-8")
    shutil.copy2(ROOT / "scripts" / "sync_codex_plugin_skill.py", scripts)

    result = subprocess.run(
        [sys.executable, "scripts/sync_codex_plugin_skill.py", "--check"],
        cwd=temporary_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "content differs: SKILL.md" in result.stderr


def test_version_matches_engine_version() -> None:
    manifest = load_json(MANIFEST_PATH)
    version_text = (ROOT / "skills" / PLUGIN_NAME / "scripts" / "version.py").read_text(encoding="utf-8")
    version_line = next(line for line in version_text.splitlines() if line.startswith("ENGINE_VERSION"))
    engine_version = version_line.split("=", 1)[1].strip().strip("'\"")
    assert manifest["version"] == engine_version


def test_plugin_description_guardrails() -> None:
    manifest_text = MANIFEST_PATH.read_text(encoding="utf-8")
    readme_text = (PLUGIN_ROOT / "README.md").read_text(encoding="utf-8")
    public_copy = f"{manifest_text}\n{readme_text}"
    required = [
        "Apache-2.0",
        "local-first",
        "white-box hedonic regression",
        "comparable transaction analysis",
        "Excel and JSON",
        "does not send input files to external services",
        "not real-estate appraisal opinions",
        "final decision remains with the user",
    ]
    for phrase in required:
        assert phrase in public_copy

    forbidden_claims = [
        "正確な土地価格を自動算定",
        "鑑定評価を自動化",
        "完全自動査定",
        "誰でも正しい価格を出せる",
        "AIが最適価格を決定",
        "不動産鑑定士が不要になる",
        "accurate land prices",
        "automates appraisal",
        "fully automated valuation",
    ]
    for phrase in forbidden_claims:
        assert phrase not in public_copy


def test_no_private_or_secret_artifacts_are_packaged() -> None:
    forbidden_names = {".env", "id_rsa", "id_ed25519"}
    forbidden_suffixes = {".pem", ".key", ".p12", ".pfx", ".docx", ".pdf", ".xlsx", ".xls"}
    packaged = [
        path.relative_to(PLUGIN_ROOT)
        for path in PLUGIN_ROOT.rglob("*")
        if path.is_file()
        and (path.name in forbidden_names or path.suffix.lower() in forbidden_suffixes)
    ]
    assert packaged == []


def test_packaged_plugin_excludes_pr_handoff_notes() -> None:
    assert not (PACKAGED_SKILL / "PR_HANDOFF.md").exists()


def test_claude_plugin_related_files_are_not_part_of_codex_package() -> None:
    changed = subprocess.run(
        ["git", "diff", "--name-only", "main...HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    assert not any(path.startswith("claude-plugins/") for path in changed)


def test_valuation_logic_files_are_not_changed() -> None:
    changed = subprocess.run(
        ["git", "diff", "--name-only", "main...HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    logic_prefix = f"skills/{PLUGIN_NAME}/scripts/"
    assert not any(path.startswith(logic_prefix) for path in changed)
