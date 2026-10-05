"""
test_recyclarr_config_directory_contract.py — Testinfra contract tests for the
deployed Recyclarr configuration directory on The Host.

Spec anchor:
    Recyclarr v8 loads EVERY *.yml under /config/configs/ in addition to
    /config/recyclarr.yml. Stray template files there (e.g. created by
    `recyclarr config create -t web-1080p -t hd-bluray-web`) define duplicate
    instances at the same base URLs and abort every sync with a
    "Split Instances" configuration error.
    Reference: https://recyclarr.dev/guide/file-structure/

Regression history:
    A leftover configs/web-1080p.yml + configs/hd-bluray-web.yml pair produced
    the "Split Instances" abort on The Host: both official-template instances
    (web-1080p / hd-bluray-web) and the SSOT instances (sonarr / radarr) were
    bound to the same base URLs. The configuration role now purges the
    directory on every provisioning run.

Contracts:
    1. The managed configuration set is present with the expected ownership
       and permissions (recyclarr.yml, settings.yml, custom-formats/*).
    2. /opt/mediastack/appdata/recyclarr/configs is absent — or, if Recyclarr
       ever recreates it, contains no *.yml / *.yaml files.
    3. The configuration role carries the idempotent purge task that keeps
       contract 2 true across provisioning runs.

Conventions:
    - Unlike the sibling template-only tests, THESE assertions consult the
      `host` fixture: they verify runtime state of The Host after converge.
"""

from pathlib import Path

import pytest
import yaml


# ---------------------------------------------------------------------------
# Repo layout + deployment paths (single source of truth)
# ---------------------------------------------------------------------------
_THIS_FILE = Path(__file__).resolve()
REPO_ROOT = _THIS_FILE.parents[3]

CONFIGURATION_ROLE_TASKS = (
    REPO_ROOT / "ansible" / "roles" / "configuration" / "tasks" / "main.yml"
)

RECYCLARR_APPDATA = Path("/opt/mediastack/appdata/recyclarr")
RECYCLARR_CONFIGS_DIR = RECYCLARR_APPDATA / "configs"

# (path, expected mode) pairs for every file the configuration role must have
# deployed into the Recyclarr appdata directory.
MANAGED_FILES = (
    (RECYCLARR_APPDATA / "recyclarr.yml", 0o600),
    (RECYCLARR_APPDATA / "settings.yml", 0o600),
    (
        RECYCLARR_APPDATA / "custom-formats" / "sonarr"
        / "language-prefer-dutch.json",
        0o644,
    ),
    (
        RECYCLARR_APPDATA / "custom-formats" / "radarr"
        / "language-prefer-dutch.json",
        0o644,
    ),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _load_role_tasks() -> list:
    """Parse the configuration role's task list as YAML."""
    raw = CONFIGURATION_ROLE_TASKS.read_text(encoding="utf-8")
    try:
        doc = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        pytest.fail(f"configuration role task file is not valid YAML: {exc}")
    assert isinstance(doc, list), "the role task file must be a YAML list"
    return doc


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_managed_recyclarr_config_files_present(host):
    """
    The configuration role MUST have deployed the managed Recyclarr file set
    into /opt/mediastack/appdata/recyclarr with mediasvc ownership
    (Zero Root Execution, AGENTS.md §3) and the expected modes.
    """
    for path, expected_mode in MANAGED_FILES:
        deployed = host.file(str(path))
        assert deployed.exists, (
            f"Managed Recyclarr file missing on The Host: {path}"
        )
        assert deployed.user == "mediasvc", (
            f"{path} must be owned by mediasvc (Zero Root Execution, "
            f"AGENTS.md §3); found owner {deployed.user!r}"
        )
        assert deployed.mode == expected_mode, (
            f"{path} must have mode {oct(expected_mode)}; "
            f"found {oct(deployed.mode)}"
        )


def test_no_stray_recyclarr_config_files(host):
    """
    /opt/mediastack/appdata/recyclarr/configs MUST be absent — or, if
    Recyclarr ever recreates it, contain no *.yml / *.yaml files.

    Recyclarr v8 auto-loads EVERY YAML file under configs/ in addition to
    recyclarr.yml. Stray template files (web-1080p.yml, hd-bluray-web.yml)
    re-introduce duplicate instances at the same base URLs and abort every
    sync with a "Split Instances" configuration error.
    """
    configs_dir = host.file(str(RECYCLARR_CONFIGS_DIR))
    if not configs_dir.exists:
        # Ideal state: the purge task removed the directory entirely.
        return

    listing = host.run(
        f"find {RECYCLARR_CONFIGS_DIR} -maxdepth 1 -type f "
        "\\( -name '*.yml' -o -name '*.yaml' \\)"
    )
    assert listing.rc == 0, (
        f"Failed to inspect {RECYCLARR_CONFIGS_DIR}: {listing.stderr}"
    )
    assert listing.stdout.strip() == "", (
        "Recyclarr auto-loads EVERY *.yml under configs/ in addition to "
        "recyclarr.yml; the following stray files re-introduce the "
        "'Split Instances' sync abort:\n" + listing.stdout
    )


def test_configuration_role_purges_stale_config_templates(host):
    """
    The configuration role MUST carry the idempotent purge task
    (ansible.builtin.file, state: absent) for the configs directory, so the
    anti-"Split Instances" contract is enforced on every provisioning run.
    """
    tasks = _load_role_tasks()
    purge_tasks = [
        task
        for task in tasks
        if isinstance(task, dict)
        and isinstance(task.get("ansible.builtin.file"), dict)
        and task["ansible.builtin.file"].get("path")
        == "/opt/mediastack/appdata/recyclarr/configs"
        and task["ansible.builtin.file"].get("state") == "absent"
    ]
    assert purge_tasks, (
        "The configuration role must purge "
        "/opt/mediastack/appdata/recyclarr/configs (state: absent). "
        "Recyclarr loads every *.yml there in addition to recyclarr.yml; "
        "stale template files cause the 'Split Instances' sync abort."
    )
    assert "configuration" in (purge_tasks[0].get("tags") or []), (
        "The purge task must carry the `configuration` tag like its siblings"
    )

