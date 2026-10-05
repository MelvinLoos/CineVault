"""
test_recyclarr_dutch_prioritisation.py — Testinfra contract tests for the
Dutch prioritisation features of the Recyclarr v8 sync configuration.

Spec anchor:
    TRaSH Guides: "[Streaming Services] Dutch" custom-format groups
    (sonarr/cf-groups/streaming-services-dutch.json,
     radarr/cf-groups/streaming-services-dutch.json) and
    "How to set up Language Custom Formats" (docs/Radarr/Tips/).

Contracts (three legs):
    1. Both the sonarr and radarr sections enable the official
       [Streaming Services] Dutch custom-format group with the exact TRaSH
       trash_ids (f60f4401ce880aad62e9d21c8bb6b91a /
       088a792e0561c927fb396664b0db5c8f). Each group contains only required
       CFs, so enabling the group is the entire sync.
    2. Both sections sync a locally shipped "Language: Prefer Dutch" custom
       format (+10 for Dutch/Flemish audio) onto their guide-backed quality
       profile. The CF is shipped from
       ansible/files/recyclarr/custom-formats/<service>/ because TRaSH
       publishes it as "guide-only" (placeholder trash_id → not syncable
       from the official collection).
    3. settings.yml.j2 declares the `custom-formats` resource providers that
       make the local CFs visible to Recyclarr, and the shipped JSON mirrors
       the TRaSH guide-only reference (Dutch=7, Flemish=19, score +10).

Conventions:
    - Accepts the `host` testinfra fixture (matching the sibling tests) so
      the tests are collected by the Molecule verifier under the `[local]`
      parametrisation. The fixture is not consulted: these assertions are
      over repository templates, not runtime state of The Host.
"""

import json
import re
from pathlib import Path

import pytest
import yaml


# ---------------------------------------------------------------------------
# Repo layout — single source of truth for the template/file paths
# ---------------------------------------------------------------------------
# This file lives at:
#     <repo>/molecule/default/tests/test_recyclarr_dutch_prioritisation.py
# So the repo root is three parents up.
_THIS_FILE = Path(__file__).resolve()
REPO_ROOT = _THIS_FILE.parents[3]

RECYCLARR_TEMPLATE = REPO_ROOT / "ansible" / "files" / "recyclarr" / "recyclarr.yml.j2"
SETTINGS_TEMPLATE = REPO_ROOT / "ansible" / "files" / "recyclarr" / "settings.yml.j2"
CUSTOM_FORMATS_DIR = REPO_ROOT / "ansible" / "files" / "recyclarr" / "custom-formats"

# TRaSH Guides trash_ids mirrored from the official group definitions:
#   sonarr/cf-groups/streaming-services-dutch.json
#   radarr/cf-groups/streaming-services-dutch.json
SONARR_DUTCH_STREAMING_GROUP_TRASH_ID = "f60f4401ce880aad62e9d21c8bb6b91a"
RADARR_DUTCH_STREAMING_GROUP_TRASH_ID = "088a792e0561c927fb396664b0db5c8f"

# The guide-backed quality profiles the Dutch preference CF is scored onto.
SONARR_WEB_1080P_TRASH_ID = "72dae194fc92bf828f32cde7744e51a1"
RADARR_HD_BLURAY_WEB_TRASH_ID = "d1d67249d3890e49bc12e275d989a7e9"

# Locally owned stable trash_ids for the shipped "Language: Prefer Dutch" CF
# (TRaSH guide-only CFs carry the non-syncable placeholder id "guide-only").
DUTCH_PREFER_CF_TRASH_ID = {
    "sonarr": "f8318a20e9e8a8680aeb59bd5bf70dd0",
    "radarr": "ab5925ee79196232e7b91e477cd4703e",
}

# Expected language ids inside the CF's LanguageSpecification per TRaSH:
#   docs/json/guide-only/language-prefer-dutch.json
DUTCH_LANGUAGE_ID = 7
FLEMISH_LANGUAGE_ID = 19
EXPECTED_DUTCH_PREFER_SCORE = 10


# ---------------------------------------------------------------------------
# Jinja → parseable text rendering helpers (mirrors the sibling test module)
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


def _render_template(path: Path) -> str:
    """
    Read a Jinja template and return a best-effort 'rendered' string suitable
    for YAML parsing. Jinja expressions are replaced with a neutral
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


def _load_yaml_template(path: Path, label: str) -> dict:
    """Render a Jinja template and parse it as YAML."""
    rendered = _render_template(path)
    try:
        doc = yaml.safe_load(rendered)
    except yaml.YAMLError as exc:
        pytest.fail(
            f"Failed to parse the rendered {label} as YAML.\n"
            f"  Template path : {path}\n"
            f"  YAML error    : {exc}\n"
            "Recyclarr would reject this file before any sync attempt."
        )
    assert isinstance(doc, dict), f"{label} must be a mapping"
    return doc


def _load_recyclarr_doc() -> dict:
    """Render the Recyclarr template and parse it as YAML."""
    return _load_yaml_template(RECYCLARR_TEMPLATE, "Recyclarr Sync Template")


def _load_settings_doc() -> dict:
    """Render the Recyclarr settings template and parse it as YAML."""
    return _load_yaml_template(SETTINGS_TEMPLATE, "Recyclarr Settings Template")


def _group_trash_ids(instance: dict) -> list:
    """Return every trash_id declared under custom_format_groups.add."""
    groups = (instance.get("custom_format_groups") or {}).get("add") or []
    trash_ids = []
    for group in groups:
        assert isinstance(group, dict), (
            "every custom_format_groups.add entry must be a mapping"
        )
        if "trash_id" in group:
            trash_ids.append(group["trash_id"])
    return trash_ids


def _custom_format_entry(instance: dict, cf_trash_id: str):
    """Return the custom_formats entry referencing cf_trash_id, or None."""
    for entry in instance.get("custom_formats") or []:
        assert isinstance(entry, dict), (
            "every custom_formats entry must be a mapping"
        )
        if cf_trash_id in (entry.get("trash_ids") or []):
            return entry
    return None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_dutch_streaming_services_group_enabled(host):
    """
    Both services MUST enable the official [Streaming Services] Dutch group:

      - Sonarr: f60f4401ce880aad62e9d21c8bb6b91a (NLZ + VDL)
      - Radarr: 088a792e0561c927fb396664b0db5c8f (Pathé + VDL)

    The groups contain only required custom formats, so enabling the group
    is the entire sync — Recyclarr applies the guide scores automatically.
    """
    doc = _load_recyclarr_doc()

    sonarr_ids = _group_trash_ids(doc["sonarr"]["sonarr"])
    assert SONARR_DUTCH_STREAMING_GROUP_TRASH_ID in sonarr_ids, (
        "The sonarr section must enable the [Streaming Services] Dutch group "
        f"(trash_id {SONARR_DUTCH_STREAMING_GROUP_TRASH_ID})"
    )

    radarr_ids = _group_trash_ids(doc["radarr"]["radarr"])
    assert RADARR_DUTCH_STREAMING_GROUP_TRASH_ID in radarr_ids, (
        "The radarr section must enable the [Streaming Services] Dutch group "
        f"(trash_id {RADARR_DUTCH_STREAMING_GROUP_TRASH_ID})"
    )

    # Anti-regression on the raw rendered text: the group entries must be
    # ACTIVE (no leading `#`), which the YAML parse above already implies —
    # this pins the exact line shape so a future edit cannot silently
    # re-comment the feature.
    rendered = _render_template(RECYCLARR_TEMPLATE)
    for group_id in (
        SONARR_DUTCH_STREAMING_GROUP_TRASH_ID,
        RADARR_DUTCH_STREAMING_GROUP_TRASH_ID,
    ):
        pattern = re.compile(
            rf"^\s*-\s*trash_id:\s*{group_id}\b", re.MULTILINE
        )
        assert pattern.search(rendered), (
            f"The [Streaming Services] Dutch group entry {group_id} must be "
            "an active (uncommented) add: list item"
        )


def test_dutch_language_preference_scored_on_quality_profiles(host):
    """
    Both services MUST sync the local "Language: Prefer Dutch" custom format
    (+10) onto their guide-backed quality profile:

      - Sonarr → WEB-1080p          (72dae194fc92bf828f32cde7744e51a1)
      - Radarr → HD Bluray + WEB    (d1d67249d3890e49bc12e275d989a7e9)
    """
    doc = _load_recyclarr_doc()

    for service, profile_trash_id in (
        ("sonarr", SONARR_WEB_1080P_TRASH_ID),
        ("radarr", RADARR_HD_BLURAY_WEB_TRASH_ID),
    ):
        instance = doc[service][service]
        cf_trash_id = DUTCH_PREFER_CF_TRASH_ID[service]
        entry = _custom_format_entry(instance, cf_trash_id)

        assert entry is not None, (
            f"The {service} section must sync the local 'Language: Prefer "
            f"Dutch' custom format (trash_id {cf_trash_id})"
        )
        assert entry.get("score") == EXPECTED_DUTCH_PREFER_SCORE, (
            f"'Language: Prefer Dutch' must be scored "
            f"{EXPECTED_DUTCH_PREFER_SCORE} for {service} "
            f"(found: {entry.get('score')!r})"
        )
        assert entry.get("assign_scores_to") == [
            {"trash_id": profile_trash_id}
        ], (
            f"'Language: Prefer Dutch' must be assigned to the {service} "
            f"guide-backed profile {profile_trash_id} only "
            f"(found: {entry.get('assign_scores_to')!r})"
        )

    # Raw-text anti-regression: the CF must be referenced as an active list
    # item inside `trash_ids:`.
    rendered = _render_template(RECYCLARR_TEMPLATE)
    for cf_trash_id in DUTCH_PREFER_CF_TRASH_ID.values():
        pattern = re.compile(
            rf"^\s*-\s*{cf_trash_id}\s+#\s+Language: Prefer Dutch\s*$",
            re.MULTILINE,
        )
        assert pattern.search(rendered), (
            f"The 'Language: Prefer Dutch' trash_id {cf_trash_id} must be an "
            "active (uncommented) trash_ids: list item"
        )


def test_shipped_custom_format_mirrors_trash_guide_only_reference(host):
    """
    The locally shipped "Language: Prefer Dutch" JSON files MUST mirror the
    TRaSH Guides guide-only reference
    (docs/json/guide-only/language-prefer-dutch.json):

      - name "Language: Prefer Dutch", score +10
      - LanguageSpecification: Dutch (7) OR Flemish (19), non-negated
      - a stable, unique, repo-owned trash_id (32 hex chars) per service
    """
    for service, trash_id in DUTCH_PREFER_CF_TRASH_ID.items():
        path = CUSTOM_FORMATS_DIR / service / "language-prefer-dutch.json"
        assert path.exists(), (
            f"Missing shipped custom format for {service}: {path}"
        )
        try:
            cf = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            pytest.fail(
                f"Shipped custom format is not valid JSON: {path}\n"
                f"  JSON error: {exc}"
            )

        assert cf.get("name") == "Language: Prefer Dutch", (
            f"{path} must declare name 'Language: Prefer Dutch'"
        )
        assert cf.get("trash_id") == trash_id, (
            f"{path} must declare the stable trash_id {trash_id} "
            "(referenced from recyclarr.yml.j2)"
        )
        assert re.fullmatch(r"[0-9a-f]{32}", str(cf.get("trash_id"))), (
            f"{path} trash_id must be a 32-char lowercase hex string"
        )
        assert (cf.get("trash_scores") or {}).get("default") == (
            EXPECTED_DUTCH_PREFER_SCORE
        ), f"{path} must default-score +{EXPECTED_DUTCH_PREFER_SCORE}"

        specs = cf.get("specifications") or []
        assert specs, f"{path} must declare at least one specification"
        lang_specs = [
            spec
            for spec in specs
            if spec.get("implementation") == "LanguageSpecification"
        ]
        lang_values = {spec["fields"]["value"] for spec in lang_specs}
        assert lang_values == {DUTCH_LANGUAGE_ID, FLEMISH_LANGUAGE_ID}, (
            f"{path} must match Dutch ({DUTCH_LANGUAGE_ID}) OR Flemish "
            f"({FLEMISH_LANGUAGE_ID}) audio (found: {sorted(lang_values)})"
        )
        for spec in lang_specs:
            assert spec.get("negate") is False, (
                f"{path}: specifications must be non-negated (match, not "
                "reverse-score)"
            )


def test_settings_declares_custom_formats_resource_providers(host):
    """
    settings.yml MUST expose the shipped custom formats to Recyclarr through
    `custom-formats` resource providers — the documented mechanism for
    syncing custom formats that are not part of the official collection
    (https://recyclarr.dev/reference/settings/resource-providers/).

    The provider path must line up with the Ansible deploy destination:
        /opt/mediastack/appdata/recyclarr/custom-formats/<service>
        → /config/custom-formats/<service> inside the container.
    """
    doc = _load_settings_doc()
    providers = doc.get("resource_providers") or []
    assert providers, (
        "settings.yml must declare resource_providers for the shipped "
        "custom formats"
    )

    by_service = {
        provider.get("service"): provider
        for provider in providers
        if isinstance(provider, dict)
    }

    for service in ("sonarr", "radarr"):
        provider = by_service.get(service)
        assert provider is not None, (
            f"settings.yml must declare a resource provider for {service} "
            "(custom-formats type) exposing the shipped Dutch CF"
        )
        assert provider.get("type") == "custom-formats", (
            f"the {service} resource provider must have type "
            f"'custom-formats' (found: {provider.get('type')!r})"
        )
        assert provider.get("path") == f"/config/custom-formats/{service}", (
            f"the {service} resource provider path must be "
            f"'/config/custom-formats/{service}' so it resolves inside the "
            "existing ./appdata/recyclarr bind mount "
            f"(found: {provider.get('path')!r})"
        )

    # Wiring cross-check: every provider directory exists in the repository
    # and the CF it ships is referenced from recyclarr.yml.j2.
    doc_recyclarr = _load_recyclarr_doc()
    for service, trash_id in DUTCH_PREFER_CF_TRASH_ID.items():
        assert (CUSTOM_FORMATS_DIR / service).is_dir(), (
            f"Missing provider directory: {CUSTOM_FORMATS_DIR / service}"
        )
        entry = _custom_format_entry(
            doc_recyclarr[service][service], trash_id
        )
        assert entry is not None, (
            f"recyclarr.yml.j2 must reference the shipped {service} custom "
            f"format trash_id {trash_id}"
        )
