"""
test_sonarr_sabnzbd_category_sync.py — Testinfra contract tests for the
Recyclarr v8 sync config and the Sonarr ⇄ SABnzbd Category Tag.

Spec anchor:
    .ruler/specs/active/bug-sonarr-sabnzbd-sync.md

History:
    The original bug hypothesis blamed Recyclarr sync for breaking the
    Sonarr ⇄ SABnzbd download link ("Download wasn't grabbed by sonarr,
    skipping"). The original remediation injected a `download_clients`
    block into recyclarr.yml.j2 so it could be string-compared against
    config.xml.j2. That key is NOT part of the Recyclarr v8 schema
    (`additionalProperties: false` on instance configs): the strict parser
    rejects the whole file and every sync run fails. It was also a
    layering violation — Recyclarr (Maintenance context) does not own the
    Acquisition ⇄ Processing category contract.

Current contract (three legs):
    1. Recyclarr config must be v8-schema-valid: no `download_clients`
       key, no removed `include: template:` directives, only v8 keys.
    2. The v8 sync targets must mirror the official TRaSH Guides
       templates: Sonarr WEB-1080p and Radarr HD Bluray + WEB.
    3. The Sonarr ⇄ SABnzbd Category Tag remains a strict SSOT contract:
       provision_host.yml defines `sonarr_sabnzbd_category` and
       config.xml.j2 references exactly that variable inside the SABnzbd
       <DownloadClient> block. Recyclarr carries no category literal.

Conventions:
    - Accepts the `host` testinfra fixture (matching the sibling tests) so
      the tests are collected by the Molecule verifier under the `[local]`
      parametrisation. The fixture is not consulted: these assertions are
      over repository templates, not runtime state of The Host.
"""

import re
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
import yaml


# ---------------------------------------------------------------------------
# Repo layout — single source of truth for the template/playbook paths
# ---------------------------------------------------------------------------
# This file lives at:
#     <repo>/molecule/default/tests/test_sonarr_sabnzbd_category_sync.py
# So the repo root is three parents up.
_THIS_FILE = Path(__file__).resolve()
REPO_ROOT = _THIS_FILE.parents[3]

RECYCLARR_TEMPLATE = REPO_ROOT / "ansible" / "files" / "recyclarr" / "recyclarr.yml.j2"
SONARR_CONFIG_TEMPLATE = REPO_ROOT / "ansible" / "files" / "servarr" / "config.xml.j2"
PROVISION_PLAYBOOK = REPO_ROOT / "ansible" / "playbooks" / "provision_host.yml"

# The SSOT Ansible variable name that links Sonarr ⇄ SABnzbd.
SSOT_CATEGORY_VAR = "sonarr_sabnzbd_category"

# Recyclarr v8 schema: the only keys allowed on a sonarr/radarr instance
# (https://schemas.recyclarr.dev/latest/config-schema.json,
#  $defs.sonarr_instance / $defs.radarr_instance, additionalProperties: false).
V8_VALID_INSTANCE_KEYS = frozenset(
    {
        "base_url",
        "api_key",
        "quality_definition",
        "quality_profiles",
        "custom_formats",
        "custom_format_groups",
        "include",
        "media_naming",
        "media_management",
        "delete_old_custom_formats",
    }
)

# TRaSH Guides trash_ids mirrored from the official config templates:
#   sonarr/templates/web-1080p.yml, radarr/templates/hd-bluray-web.yml
SONARR_WEB_1080P_TRASH_ID = "72dae194fc92bf828f32cde7744e51a1"
RADARR_HD_BLURAY_WEB_TRASH_ID = "d1d67249d3890e49bc12e275d989a7e9"


# ---------------------------------------------------------------------------
# Jinja → parseable text rendering helpers
#
# We do NOT execute Ansible to render the templates (it would require the
# full inventory + vault). Instead, we strip Jinja control structures and
# replace `{{ ... }}` expressions with a neutral placeholder string. This
# preserves the literal text outside Jinja markers — which is exactly what
# the assertions below inspect.
# ---------------------------------------------------------------------------

# Matches `{{ ... }}` expressions (non-greedy, single line — Jinja
# expressions in these templates are single-line).
_JINJA_EXPR_RE = re.compile(r"\{\{.*?\}\}")
# Matches `{% ... %}` statements (for/if/etc). Replaced with empty string.
_JINJA_STMT_RE = re.compile(r"\{%..*?%\}", re.DOTALL)
# Matches `{# ... #}` comments.
_JINJA_COMMENT_RE = re.compile(r"\{#.*?#\}", re.DOTALL)

_NEUTRAL_PLACEHOLDER = "__RENDERED_PLACEHOLDER__"

# A `download_clients:` mapping key line (anti-regression: this key was
# never part of the Recyclarr schema and breaks config parsing).
_DOWNLOAD_CLIENTS_KEY_RE = re.compile(r"^\s*download_clients\s*:", re.MULTILINE)

# The SSOT variable reference inside Sonarr's SABnzbd download-client
# category element, e.g. <Category>{{ sonarr_sabnzbd_category }}</Category>.
_SONARR_CATEGORY_SSOT_RE = re.compile(
    r"<Category>\s*\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}\s*</Category>"
)


def _render_template(path: Path) -> str:
    """
    Read a Jinja template and return a best-effort 'rendered' string suitable
    for YAML/XML parsing. Jinja expressions are replaced with a neutral
    placeholder; statements and comments are stripped.

    This intentionally does NOT touch the literal text outside Jinja
    markers, which is precisely where the assertions below look.
    """
    assert path.exists(), f"Required template not found at {path}"
    raw = path.read_text(encoding="utf-8")
    rendered = _JINJA_COMMENT_RE.sub("", raw)
    rendered = _JINJA_STMT_RE.sub("", rendered)
    rendered = _JINJA_EXPR_RE.sub(_NEUTRAL_PLACEHOLDER, rendered)
    return rendered


def _load_recyclarr_doc() -> dict:
    """Render the Recyclarr template and parse it as YAML."""
    rendered = _render_template(RECYCLARR_TEMPLATE)
    try:
        doc = yaml.safe_load(rendered)
    except yaml.YAMLError as exc:
        pytest.fail(
            "Failed to parse the rendered Recyclarr Sync Template as YAML.\n"
            f"  Template path : {RECYCLARR_TEMPLATE}\n"
            f"  YAML error    : {exc}\n"
            "Recyclarr would reject this file before any sync attempt."
        )
    assert isinstance(doc, dict), "Recyclarr config must be a mapping"
    return doc


def _load_playbook_vars() -> dict:
    """Load the `vars:` block of the provision_host.yml play."""
    raw = PROVISION_PLAYBOOK.read_text(encoding="utf-8")
    try:
        doc = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        pytest.fail(
            f"Failed to parse the provisioning playbook as YAML: {exc}"
        )
    if not isinstance(doc, list) or not doc or not isinstance(doc[0], dict):
        pytest.fail("provision_host.yml must contain a play as its first document")
    return doc[0].get("vars") or {}



def _extract_sonarr_config_category(rendered_xml: str):
    """
    Parse the rendered Sonarr Config Template and return the SABnzbd
    download-client Category Tag, or None if none is declared.

    Sonarr's config.xml structure for download clients:

        <Config>
          ...
          <DownloadClients>
            <DownloadClient>
              <Name>sabnzbd</Name>
              <Implementation>Sabnzbd</Implementation>
              <Category>tv-sonarr</Category>    <-- the value we extract
              ...
            </DownloadClient>
          </DownloadClients>
        </Config>
    """
    try:
        root = ET.fromstring(rendered_xml)
    except ET.ParseError as exc:
        pytest.fail(
            "Failed to parse the rendered Sonarr Config Template as XML.\n"
            f"  Template path : {SONARR_CONFIG_TEMPLATE}\n"
            f"  XML error     : {exc}\n"
        )

    # 1) Preferred: a <DownloadClient> with an explicit SABnzbd implementation.
    for client in root.iter("DownloadClient"):
        impl = client.findtext("Implementation", default="").strip().lower()
        name = client.findtext("Name", default="").strip().lower()
        if "sab" in impl or "sab" in name:
            cat = client.findtext("Category")
            if cat is not None:
                return cat.strip()

    # 2) Any <DownloadClient> with a Category element (first wins).
    for client in root.iter("DownloadClient"):
        cat = client.findtext("Category")
        if cat is not None:
            return cat.strip()

    return None



# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_recyclarr_config_uses_only_v8_schema_keys(host):
    """
    The Recyclarr Sync Template MUST be parseable as YAML and contain only
    keys that exist in the Recyclarr v8 schema. The strict parser rejects
    unknown keys (additionalProperties: false) — most notably the legacy
    `download_clients` key and the removed `include: template:` directive —
    which would abort every sync run for BOTH Radarr and Sonarr.
    """
    doc = _load_recyclarr_doc()

    assert set(doc.keys()) == {"sonarr", "radarr"}, (
        "Recyclarr config must define exactly the sonarr and radarr services"
    )

    for service, instances in doc.items():
        assert isinstance(instances, dict), (
            f"{service!r} instances must use the v8 named-style mapping "
            "(array-style instance lists were removed in v5)"
        )
        for instance_name, instance in instances.items():
            assert isinstance(instance, dict), (
                f"Instance {service!r}.{instance_name!r} must be a mapping"
            )
            unknown_keys = set(instance) - V8_VALID_INSTANCE_KEYS
            assert not unknown_keys, (
                f"Instance {service!r}.{instance_name!r} uses keys that are "
                f"invalid under the Recyclarr v8 schema: {sorted(unknown_keys)}"
            )
            assert "download_clients" not in instance, (
                f"Instance {service!r}.{instance_name!r} declares "
                "'download_clients', which is not a Recyclarr config key — "
                "the strict v8 parser rejects the whole config"
            )
            # `include: template:` was removed in v8: the official
            # config-templates repo no longer ships include templates.
            for directive in instance.get("include") or []:
                assert "template" not in directive, (
                    f"Instance {service!r}.{instance_name!r} uses an include "
                    "template directive; include templates were removed in "
                    "Recyclarr v8"
                )

    # Anti-regression on the raw rendered text: no `download_clients:` key
    # line may exist anywhere (comments are exempt by the regex anchor).
    rendered = _render_template(RECYCLARR_TEMPLATE)
    assert not _DOWNLOAD_CLIENTS_KEY_RE.search(rendered), (
        "recyclarr.yml.j2 must not contain a `download_clients:` key; "
        "Recyclarr does not manage download clients"
    )



def test_recyclarr_v8_sync_targets_match_trash_guides_templates(host):
    """
    The v8 sync targets MUST mirror the official TRaSH Guides templates:
      - Sonarr: WEB-1080p quality profile + series quality definition
      - Radarr: HD Bluray + WEB quality profile + movie quality definition
    """
    doc = _load_recyclarr_doc()

    sonarr = doc["sonarr"]["sonarr"]
    assert sonarr["quality_definition"]["type"] == "series", (
        "Sonarr quality definition must be type 'series' (WEB-1080p template)"
    )
    sonarr_qps = sonarr["quality_profiles"]
    assert sonarr_qps and sonarr_qps[0]["trash_id"] == SONARR_WEB_1080P_TRASH_ID, (
        "Sonarr must sync the TRaSH Guides WEB-1080p quality profile "
        f"(trash_id {SONARR_WEB_1080P_TRASH_ID})"
    )
    assert sonarr_qps[0]["reset_unmatched_scores"]["enabled"] is True
    assert sonarr["custom_format_groups"]["add"], (
        "Sonarr custom format groups must be populated (web-1080p template)"
    )

    radarr = doc["radarr"]["radarr"]
    assert radarr["quality_definition"]["type"] == "movie", (
        "Radarr quality definition must be type 'movie' (hd-bluray-web template)"
    )
    radarr_qps = radarr["quality_profiles"]
    assert radarr_qps and radarr_qps[0]["trash_id"] == RADARR_HD_BLURAY_WEB_TRASH_ID, (
        "Radarr must sync the TRaSH Guides HD Bluray + WEB quality profile "
        f"(trash_id {RADARR_HD_BLURAY_WEB_TRASH_ID})"
    )
    assert radarr_qps[0]["reset_unmatched_scores"]["enabled"] is True
    assert radarr["custom_format_groups"]["add"], (
        "Radarr custom format groups must be populated (hd-bluray-web template)"
    )



def test_sonarr_category_tag_single_source_of_truth(host):
    """
    The Sonarr ⇄ SABnzbd Category Tag MUST remain a strict SSOT contract:

      - provision_host.yml defines `sonarr_sabnzbd_category` (non-empty).
      - config.xml.j2 references exactly that variable inside the SABnzbd
        <DownloadClient> block — no hardcoded category literal.
      - recyclarr.yml.j2 carries neither a category literal nor any
        download-client routing keys (layering integrity).

    A divergence here is the canonical cause of:
        "Download wasn't grabbed by sonarr, skipping"
    because Sonarr uses the Category Tag as the join key when polling
    SABnzbd for its own queued grabs.
    """
    # 1) The playbook defines the SSOT variable with a non-empty value.
    play_vars = _load_playbook_vars()
    ssot_value = play_vars.get(SSOT_CATEGORY_VAR)
    assert ssot_value, (
        f"The SSOT variable {SSOT_CATEGORY_VAR!r} must be defined with a "
        "non-empty value in the provision_host.yml `vars:` block"
    )

    # 2) config.xml.j2 references exactly that variable name inside the
    #    SABnzbd download-client category element.
    config_raw = SONARR_CONFIG_TEMPLATE.read_text(encoding="utf-8")
    match = _SONARR_CATEGORY_SSOT_RE.search(config_raw)
    assert match, (
        "config.xml.j2 must declare a SABnzbd download-client "
        "<Category>{{ ... }}</Category> element"
    )
    assert match.group(1) == SSOT_CATEGORY_VAR, (
        f"config.xml.j2 must reference the SSOT variable "
        f"{SSOT_CATEGORY_VAR!r}; found {{{{ {match.group(1)} }}}}"
    )

    # 3) The rendered <Category> value must be the template placeholder —
    #    proving no hardcoded literal category exists in config.xml.j2.
    rendered_category = _extract_sonarr_config_category(
        _render_template(SONARR_CONFIG_TEMPLATE)
    )
    assert rendered_category == _NEUTRAL_PLACEHOLDER, (
        "config.xml.j2 must source the Category Tag from the SSOT variable, "
        f"not from a hardcoded literal (rendered value: {rendered_category!r})"
    )

    # 4) Layering integrity: Recyclarr must carry no category literal and
    #    no download-client routing keys.
    recyclarr_rendered = _render_template(RECYCLARR_TEMPLATE)
    assert ssot_value not in recyclarr_rendered, (
        f"recyclarr.yml.j2 must not hardcode the category literal "
        f"{ssot_value!r}; Recyclarr does not own the Sonarr ⇄ SABnzbd "
        "category contract"
    )
    assert not _DOWNLOAD_CLIENTS_KEY_RE.search(recyclarr_rendered), (
        "recyclarr.yml.j2 must not contain a `download_clients:` key; "
        "Recyclarr does not manage download clients"
    )

