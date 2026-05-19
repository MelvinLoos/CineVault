"""
test_sonarr_sabnzbd_category_sync.py — Testinfra contract test for the
Sonarr ⇄ SABnzbd Category Tag.

Spec anchor:
    .ruler/specs/active/bug-sonarr-sabnzbd-sync.md
    Acceptance Criterion #1 (TDD Mandate):
        "A Molecule Testinfra script must be created to parse both rendered
         templates and assert that the Category Tag string is strictly
         identical."

Ubiquitous Language (from the spec):
    - Recyclarr Sync Template : ansible/files/recyclarr/recyclarr.yml.j2
    - Sonarr Config Template  : ansible/files/servarr/config.xml.j2
    - Category Tag            : the strict string used to link Sonarr ⇄ SABnzbd.

Why this test exists:
    Sonarr fails to grab downloads from SABnzbd ("Download wasn't grabbed by
    sonarr, skipping").  The hypothesis is a Category Tag drift introduced by
    recent Recyclarr sync changes.  Sonarr identifies its SABnzbd download
    client by a strict category string; if the value Sonarr is configured
    with (servarr/config.xml.j2) does not exactly match the value Recyclarr
    will push (recyclarr.yml.j2), grabs fail silently.

What this test does:
    1. Resolves both template paths relative to the repo root (derived from
       this test file's location — same convention as the other Testinfra
       tests in this directory).
    2. Renders each Jinja template into safe stand-in content (placeholders
       replaced with neutral strings so YAML/XML parsing succeeds without
       requiring Ansible's full variable context).
    3. Extracts the Sonarr-side Category Tag from each:
         - Recyclarr: sonarr[*].download_clients[*].category
         - Sonarr config.xml: <DownloadClient> ... <Category>...</Category>
       (also accepts a top-level <Category> as a fallback).
    4. Asserts strict string equality between the two values.  If either is
       missing or they differ, the assertion fails with a message that names
       BOTH sources of truth and the observed values, so the operator can
       reconcile the drift immediately.

Conventions:
    - Accepts the `host` testinfra fixture (matching test_host_provision.py
      and test_unattended_upgrades.py) so the test is collected by the
      Molecule verifier under the `[local]` parametrisation.  The fixture is
      not consulted because this assertion is over repository templates, not
      over runtime state of The Host.
"""

import re
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
import yaml


# ---------------------------------------------------------------------------
# Repo layout — single source of truth for the two template paths
# ---------------------------------------------------------------------------
# This file lives at:
#     <repo>/molecule/default/tests/test_sonarr_sabnzbd_category_sync.py
# So the repo root is three parents up.
_THIS_FILE = Path(__file__).resolve()
REPO_ROOT = _THIS_FILE.parents[3]

RECYCLARR_TEMPLATE = REPO_ROOT / "ansible" / "files" / "recyclarr" / "recyclarr.yml.j2"
SONARR_CONFIG_TEMPLATE = REPO_ROOT / "ansible" / "files" / "servarr" / "config.xml.j2"


# ---------------------------------------------------------------------------
# Jinja → parseable text rendering helpers
#
# We do NOT execute Ansible to render the templates (it would require the
# full inventory + vault).  Instead, we strip Jinja control structures and
# replace `{{ ... }}` expressions with a neutral placeholder string.  This is
# sufficient because:
#   - The Category Tag itself is a LITERAL string in both templates (it must
#     be — Sonarr and Recyclarr need to agree byte-for-byte on a constant).
#   - We only need the surrounding YAML/XML structure to be parseable.
# ---------------------------------------------------------------------------

# Matches `{{ ... }}` expressions (non-greedy, single line — Jinja expressions
# in these templates are single-line).
_JINJA_EXPR_RE = re.compile(r"\{\{.*?\}\}")
# Matches `{% ... %}` statements (for/if/etc).  Replaced with empty string.
_JINJA_STMT_RE = re.compile(r"\{%.*?%\}", re.DOTALL)
# Matches `{# ... #}` comments.
_JINJA_COMMENT_RE = re.compile(r"\{#.*?#\}", re.DOTALL)

_NEUTRAL_PLACEHOLDER = "__RENDERED_PLACEHOLDER__"


def _render_template(path: Path) -> str:
    """
    Read a Jinja template and return a best-effort 'rendered' string suitable
    for YAML/XML parsing.  Jinja expressions are replaced with a neutral
    placeholder; statements and comments are stripped.

    This intentionally does NOT touch the literal text outside Jinja markers,
    which is precisely where the Category Tag lives.
    """
    assert path.exists(), f"Required template not found at {path}"
    raw = path.read_text(encoding="utf-8")
    rendered = _JINJA_COMMENT_RE.sub("", raw)
    rendered = _JINJA_STMT_RE.sub("", rendered)
    rendered = _JINJA_EXPR_RE.sub(_NEUTRAL_PLACEHOLDER, rendered)
    return rendered


# ---------------------------------------------------------------------------
# Category Tag extraction
# ---------------------------------------------------------------------------


def _extract_recyclarr_sonarr_category(rendered_yaml: str):
    """
    Parse the Recyclarr Sync Template and return the Sonarr-side
    download-client Category Tag, or None if none is declared.

    Recyclarr schema (https://recyclarr.dev/wiki/yaml/config-reference/):

        sonarr:
          - name: <instance>
            download_clients:
              - category: <CATEGORY TAG>   # <-- the value we extract
                ...

    If the template declares multiple Sonarr instances or multiple download
    clients, we return the first category encountered (the Category Tag is
    expected to be a single canonical value for the SABnzbd ⇄ Sonarr link).
    """
    try:
        doc = yaml.safe_load(rendered_yaml)
    except yaml.YAMLError as exc:
        pytest.fail(
            "Failed to parse the rendered Recyclarr Sync Template as YAML.\n"
            f"  Template path : {RECYCLARR_TEMPLATE}\n"
            f"  YAML error    : {exc}\n"
            "The test cannot extract the Category Tag from an unparseable file."
        )

    if not isinstance(doc, dict):
        return None

    sonarr_instances = doc.get("sonarr")
    if not isinstance(sonarr_instances, list):
        return None

    for instance in sonarr_instances:
        if not isinstance(instance, dict):
            continue
        clients = instance.get("download_clients")
        if not isinstance(clients, list):
            continue
        for client in clients:
            if not isinstance(client, dict):
                continue
            if "category" in client:
                return client["category"]
    return None


def _extract_sonarr_config_category(rendered_xml: str):
    """
    Parse the Sonarr Config Template and return the SABnzbd download-client
    Category Tag, or None if none is declared.

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

    We also accept a top-level <Category> element directly under <Config> as a
    fallback (some legacy layouts inline it).  We prefer the value attached to
    a SABnzbd <DownloadClient> when discriminating information is present.
    """
    try:
        root = ET.fromstring(rendered_xml)
    except ET.ParseError as exc:
        pytest.fail(
            "Failed to parse the rendered Sonarr Config Template as XML.\n"
            f"  Template path : {SONARR_CONFIG_TEMPLATE}\n"
            f"  XML error     : {exc}\n"
            "The test cannot extract the Category Tag from an unparseable file."
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

    # 3) Fallback: a Category element anywhere in the tree (e.g. inlined
    #    under <Config> directly).
    cat_el = root.find(".//Category")
    if cat_el is not None and cat_el.text is not None:
        return cat_el.text.strip()

    return None



# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_category_tag_strict_equality_between_recyclarr_and_sonarr_config(host):
    """
    The Category Tag declared by the Recyclarr Sync Template MUST be strictly
    string-equal to the Category Tag declared by the Sonarr Config Template.

    A divergence here is the canonical cause of:
        "Download wasn't grabbed by sonarr, skipping"
    failures, because Sonarr uses the Category Tag as the join key when
    polling SABnzbd for its own queued grabs.

    Sources of truth (both must agree byte-for-byte):
      - Recyclarr Sync Template  : ansible/files/recyclarr/recyclarr.yml.j2
                                   -> sonarr[*].download_clients[*].category
      - Sonarr Config Template   : ansible/files/servarr/config.xml.j2
                                   -> <DownloadClient><Category>...</Category>

    A missing value on either side is itself a divergence (None ≠ string),
    and will fail this assertion with a message naming both files.

    The `host` fixture is accepted to remain consistent with the other
    Testinfra tests in this suite (test_host_provision.py,
    test_unattended_upgrades.py); it is not consulted because this assertion
    is over repository templates, not runtime state of The Host.
    """
    # Sanity: the two source-of-truth files must actually exist.
    assert RECYCLARR_TEMPLATE.exists(), (
        f"Recyclarr Sync Template not found at {RECYCLARR_TEMPLATE}; "
        "cannot verify Category Tag sync"
    )
    assert SONARR_CONFIG_TEMPLATE.exists(), (
        f"Sonarr Config Template not found at {SONARR_CONFIG_TEMPLATE}; "
        "cannot verify Category Tag sync"
    )

    recyclarr_rendered = _render_template(RECYCLARR_TEMPLATE)
    sonarr_rendered = _render_template(SONARR_CONFIG_TEMPLATE)

    recyclarr_category = _extract_recyclarr_sonarr_category(recyclarr_rendered)
    sonarr_category = _extract_sonarr_config_category(sonarr_rendered)

    assert recyclarr_category == sonarr_category, (
        "CATEGORY TAG DRIFT — Sonarr ⇄ SABnzbd link is broken.\n"
        "The Sonarr-side download-client Category Tag must be strictly "
        "string-equal between Recyclarr and Sonarr's own config.xml; "
        "any divergence (including a missing value on either side) causes "
        "'Download wasn't grabbed by sonarr, skipping' failures.\n"
        f"  Recyclarr Sync Template : {RECYCLARR_TEMPLATE}\n"
        f"    -> sonarr[*].download_clients[*].category = {recyclarr_category!r}\n"
        f"  Sonarr Config Template  : {SONARR_CONFIG_TEMPLATE}\n"
        f"    -> <DownloadClient>/<Category>            = {sonarr_category!r}\n"
        "Reconcile both templates so these two values are byte-identical."
    )

    # Belt-and-braces: a non-empty value is required.  An empty string would
    # tie on both sides but still represent an unconfigured Category Tag.
    assert recyclarr_category, (
        "Category Tag is empty in BOTH templates; Sonarr ⇄ SABnzbd cannot "
        "be linked without a non-empty Category Tag.\n"
        f"  Recyclarr Sync Template : {RECYCLARR_TEMPLATE}\n"
        f"  Sonarr Config Template  : {SONARR_CONFIG_TEMPLATE}"
    )

