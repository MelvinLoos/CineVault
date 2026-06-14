# Bug Specification: Sonarr / SABnzbd Category Synchronization

## Context
Sonarr is failing to grab downloads from SABnzbd. The hypothesis is a category mismatch introduced by recent Recyclarr synchronization updates.

## Ubiquitous Language Mapping
* **Recyclarr Sync Template:** `ansible/files/recyclarr/recyclarr.yml.j2`
* **Sonarr Config Template:** `ansible/files/servarr/config.xml.j2`
* **Category Tag:** The strict string value used to link Sonarr and SABnzbd.

## Acceptance Criteria (TDD Mandate)
1. **Test-First:** A Molecule Testinfra script must be created to parse both rendered templates and assert that the `Category Tag` string is strictly identical.
2. **Implementation:** The templates must be modified so the tests pass, ensuring Sonarr successfully communicates with SABnzbd without the "Download wasn't grabbed by sonarr, skipping" error.

## Implementation Mandate (The SSOT Refactor)
To pass the failing test `test_category_tag_strict_equality_between_recyclarr_and_sonarr_config`, the agents MUST execute the following refactoring pattern:
1. **Variable Extraction:** Identify or create a centralized Ansible variable (e.g., `sonarr_download_client_category`) within the appropriate `group_vars` or role defaults.
2. **Template Interpolation (Recyclarr):** Inject this variable into `ansible/files/recyclarr/recyclarr.yml.j2` replacing the hardcoded category string.
3. **Template Interpolation (SABnzbd):** Inject this identical variable into the SABnzbd configuration layer (whether that is an `ini` template, a docker environment variable, or an Ansible API module payload) to ensure strict equality.
4. **No Hardcoding:** Hardcoded strings for this category tag are strictly prohibited in the `.j2` templates moving forward.