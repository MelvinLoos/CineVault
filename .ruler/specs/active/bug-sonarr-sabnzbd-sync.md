# Bug Specification: Sonarr / SABnzbd Category Synchronization

## Context
Sonarr is failing to grab downloads from SABnzbd. The hypothesis is a category mismatch introduced by recent Recyclarr synchronization updates.

## Ubiquitous Language Mapping
* **Recyclarr Sync Template:** `ansible/files/recyclarr/recyclarr.yml.j2`
* **Sonarr Config Template:** `ansible/files/servarr/config.xml.j2`
* **Category Tag:** The strict string value used to link Sonarr and SABnzbd.
* **SSOT Variable:** `sonarr_sabnzbd_category` — the single Ansible variable (defined in `provision_host.yml` `vars:`) that owns the Category Tag value.

## Acceptance Criteria (TDD Mandate)
1. **Test-First:** A Molecule Testinfra script must assert the corrected contract (see tests in `molecule/default/tests/test_sonarr_sabnzbd_category_sync.py`):
   - The Recyclarr template is v8-schema-valid (no `download_clients` key, no removed `include: template:` directives, only v8 keys).
   - The Recyclarr v8 sync targets mirror the official TRaSH Guides templates (Sonarr WEB-1080p, Radarr HD Bluray + WEB).
   - The Category Tag remains a strict SSOT contract: `config.xml.j2` references `sonarr_sabnzbd_category` and Recyclarr carries no category literal.
2. **Implementation:** The templates must be modified so the tests pass, ensuring Sonarr successfully communicates with SABnzbd without the "Download wasn't grabbed by sonarr, skipping" error.

## Implementation Mandate (The SSOT Refactor)
1. **Variable Extraction:** The Category Tag MUST live in a single Ansible variable — `sonarr_sabnzbd_category` — defined in the `provision_host.yml` `vars:` block.
2. **Template Interpolation (Sonarr):** `config.xml.j2` MUST reference `{{ sonarr_sabnzbd_category }}` inside the SABnzbd `<DownloadClient>/<Category>` element.
3. **No Hardcoding:** Hardcoded strings for this category tag are strictly prohibited in the `.j2` templates moving forward.

## Superseded Mandate (RECYCLARR DOES NOT OWN THE CATEGORY)
> The original mandate step — "inject the category variable into `recyclarr.yml.j2`" — is **superseded and MUST NOT be implemented**:
>
> 1. `download_clients` is not a valid Recyclarr config key. The v8 schema sets `additionalProperties: false` on instance configs and the strict parser rejects unknown keys, aborting every sync run for BOTH Radarr and Sonarr.
> 2. `include: - template:` directives were removed: the official config-templates repo stopped shipping include templates in v8, and the `sonarr-v3-*` template IDs died with Sonarr v3 support in v7.
> 3. Layering: Recyclarr belongs to the Maintenance bounded context (TRaSH-Guides sync). The Sonarr ⇄ SABnzbd Category Tag belongs to the Acquisition ⇄ Processing boundary, owned by `config.xml.j2` via the SSOT variable. See `docs/analysis/sonarr-sabnzbd-category-drift.md` §4.1.
>
> Recyclarr config was rewritten in v8 style (`quality_definition`, `quality_profiles`, `custom_format_groups` mirroring the official web-1080p / hd-bluray-web templates) and the image pinned to `ghcr.io/recyclarr/recyclarr:8` (upstream publishes no `latest` tag).
