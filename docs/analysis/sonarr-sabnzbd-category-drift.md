# Sonarr ↔ SABnzbd Category-Tag Drift Analysis

> **Task 2 — Read-only investigation** for *Bugfix: Sonarr–SABnzbd Recyclarr Sync*.
> This document is the input contract for Task 3 (remediation). It does **not** change
> any code, template, or test.
>
> **Anchor note:** The binding-context file `.ruler/specs/active/bug-sonarr-sabnzbd-sync.md`
> referenced by the task prompt **does not exist in this worktree** (verified by
> `find /home/melvin/.cline/worktrees/ebb2d/CineVault/.ruler -type f`). The analysis
> therefore anchors against the next-tightest authoritative sources actually present:
> `.ruler/CONSTITUTION.MD`, `.ruler/ARCHITECTURE.md`, `.ruler/PRODUCT_SPECIFICATION.md`,
> plus the two templates explicitly named in the task scope. Any conclusion that would
> have depended on a clause unique to the missing spec file is flagged inline as
> **[SPEC-GAP]**.

---

## 1. Inventory — every variable / literal that contributes to a "Category Tag"

A *Category Tag* in this stack is the short string (e.g. `tv-sonarr`, `movies-radarr`)
that:

1. Sonarr/Radarr send as the `category=` parameter on every NZB submission to SABnzbd,
   and that they store internally on the **Download Client** entry under
   *Settings → Download Clients → SABnzbd → Category*.
2. SABnzbd matches against its **Config → Categories** table to choose a per-category
   completed-download folder (typically `/data/usenet/<category>/`), priority, post-processing
   script, etc.

For the sync to work, the string on **both sides** must be byte-identical.

### 1.1 Files actually scanned

| Path | Purpose | Touches "Category Tag"? |
|------|---------|--------------------------|
| `ansible/files/recyclarr/recyclarr.yml.j2` | Recyclarr config (TRaSH-Guides sync) | **No** (see §1.2) |
| `ansible/files/servarr/config.xml.j2` | Pre-seeded Sonarr/Radarr/Prowlarr `config.xml` | **No** (see §1.3) |
| `ansible/playbooks/provision_host.yml` | Provisioning playbook — owns *all* template variables | **No** (see §1.4) |
| `ansible/inventory/hosts.ini` | Inventory for `the_host` | **No** (see §1.4) |
| `docker-compose.yml.j2` | Service definitions for SABnzbd, Sonarr, Radarr | **No** (see §1.5) |
| `ansible/files/homepage/services.yaml.j2` / `widgets.yaml.j2` | Homepage widgets | No (dashboard only) |
| `molecule/default/converge.yml` / `molecule.yml` / `tests/test_host_provision.py` | TDI harness | No |
| `.env`, `.env.example` | Compose runtime env vars | No (no `*_CATEGORY` key) |
| `ansible/credentials/*.key` | Idempotent API-key store | No (keys only) |

> **No `group_vars/`, `host_vars/`, `defaults/`, `vars/`, or `roles/` directories exist**
> anywhere in the repository
> (verified: `find … -type d \( -name group_vars -o -name host_vars -o -name defaults -o -name vars -o -name roles \)` → empty).
> **No Recyclarr `include:` template pulled from upstream defines a category either**
> (Recyclarr's TRaSH-Guides templates configure **quality profiles, custom formats, and
> quality definitions only** — categories are out of scope for Recyclarr; verified
> against <https://recyclarr.dev/wiki/yaml/config-reference/>).


### 1.2 `ansible/files/recyclarr/recyclarr.yml.j2` (21 lines, full file scanned)

| Line | Token | Kind | Resolved value (current inventory) |
|------|-------|------|-------------------------------------|
| 4    | `sonarr:` | YAML key | n/a |
| 5    | `- name: sonarr` | literal | `sonarr` (Recyclarr instance label only — **not** a SABnzbd category) |
| 6    | `base_url: http://sonarr:8989` | literal | `http://sonarr:8989` |
| 7    | `api_key: {{ sonarr_key }}` | variable | 32-char hex from `ansible/credentials/sonarr.key` (seeded via `lookup('password', …)` at playbook line 400) |
| 8-11 | `include:` block | literal templates | `sonarr-quality-definition-series`, `sonarr-v3-quality-profile-web-dl-1080p`, `sonarr-v3-custom-formats-web-dl` |
| 13   | `radarr:` | YAML key | n/a |
| 14   | `- name: radarr` | literal | `radarr` |
| 15   | `base_url: http://radarr:7878` | literal | `http://radarr:7878` |
| 16   | `api_key: {{ radarr_key }}` | variable | 32-char hex from `ansible/credentials/radarr.key` |
| 17-20 | `include:` block | literal templates | `radarr-quality-definition-movie`, `radarr-quality-profile-hd-bluray-web`, `radarr-custom-formats-hd-bluray-web` |

**Category-Tag contribution: ZERO.** There is no `download_client:` key, no
`categories:` key, no `media_management:` key, and no value-substitution variable
that mentions a category anywhere in this template. The three `include:` templates
pulled from the TRaSH-Guides repository are quality-profile / custom-format
definitions; per the Recyclarr config reference, none of these include templates
emit category configuration.

### 1.3 `ansible/files/servarr/config.xml.j2` (7 lines, full file scanned)

| Line | Token | Kind | Resolved value |
|------|-------|------|-----------------|
| 1 | `<Config>` | literal XML | n/a |
| 2 | `<Port>{{ item.port }}</Port>` | loop var | `7878` (radarr) / `8989` (sonarr) / `9696` (prowlarr) — from loop at `provision_host.yml:414-417` |
| 3 | `<BindAddress>*</BindAddress>` | literal | `*` |
| 4 | `<ApiKey>{{ item.api_key }}</ApiKey>` | loop var | `{{ radarr_key }}` / `{{ sonarr_key }}` / `{{ prowlarr_key }}` — 32-char hex |
| 5 | `<AuthenticationMethod>None</AuthenticationMethod>` | literal | `None` |
| 6 | `<UpdateMechanism>Docker</UpdateMechanism>` | literal | `Docker` |

**Category-Tag contribution: ZERO.** Sonarr's `config.xml` is the bootstrap/identity
file (port, API key, auth method). Sonarr's **Download Client** definitions —
including the `<Category>` element that pins the SABnzbd category — live inside
Sonarr's runtime database (`/config/sonarr.db`) and are **not** managed by this
template, by the playbook, or by Recyclarr.

### 1.4 `ansible/playbooks/provision_host.yml` (646 lines, full file scanned)

Every variable defined or templated by the playbook was reviewed. The category-relevant
findings:

| Line | Token | Resolved value | Relevance |
|------|-------|----------------|-----------|
| 9-11 | `vars: mediasvc_uid / mediasvc_gid / media_drive_device` | `5000 / 5000 / ""` | Not a category |
| 116-132 | appdata loop creates `…/sabnzbd`, `…/sonarr` | literal directory names | The strings `"sabnzbd"` and `"sonarr"` are *directory* names under `appdata/`, **not** SABnzbd categories. |
| 204-210 | Creates `/opt/mediastack/data/usenet/` | literal | The single shared scratch space. **No per-category sub-folder is pre-created.** Without that, SABnzbd's default behaviour is to dump completed files in `/data/usenet/<category>/`; if the category does not exist on either side the post-processing path collapses to `/data/usenet/` (root) and Sonarr import fails. |
| 397-402 | `set_fact:` for `radarr_key`, `sonarr_key`, `prowlarr_key`, `bazarr_key` | 32-char hex from `credentials/*.key` | API keys (not categories) |
| 406-419 | Template Servarr `config.xml` with loop `[{app:radarr,port:7878,…}, {app:sonarr,port:8989,…}, {app:prowlarr,port:9696,…}]` | Renders `config.xml` per app | Loop carries `port` and `api_key` — **no category field** |
| 434-442 | Templates `recyclarr.yml.j2` → `/opt/mediastack/appdata/recyclarr/recyclarr.yml` | n/a | Renders the file inventoried in §1.2 |
| 469-485 | Injects API keys into `/opt/mediastack/.env` (`RADARR_API_KEY`, `SONARR_API_KEY`, `PROWLARR_API_KEY`, `BAZARR_API_KEY`, `SABNZBD_API_KEY=""`) | Env keys | **No `*_CATEGORY` env key exists.** Note `SABNZBD_API_KEY` is intentionally empty — SABnzbd has no idempotent pre-seed yet, so SABnzbd boots from scratch with no pre-defined categories at all. |

**Category-Tag contribution: ZERO.** No Ansible variable named `*_category`,
`*_cat`, `sabnzbd_*_tag`, etc. exists. Confirmed by exhaustive grep:

```bash
$ grep -rni 'categ' --include='*.j2' --include='*.yml' --include='*.yaml' \
                    --include='*.xml' --include='*.ini' --include='*.cfg' .
# (no output)
```

### 1.5 `docker-compose.yml.j2` (lines 263-285, SABnzbd service)

| Line | Token | Resolved value | Relevance |
|------|-------|----------------|-----------|
| 263 | `sabnzbd:` | service name | not a category |
| 271-273 | `./appdata/sabnzbd:/config`, `./data:/data` | bind mounts | Provides the *space* for SABnzbd's category folders, but does **not** define any category |
| 284-285 | `ports: "8080:8080"` | literal | not a category |

No environment variable, command-line argument, or volume convention seeds a category.
SABnzbd will therefore boot with only its built-in default categories (typically
`movies`, `tv`, `audio`, `software`) — created the first time the web UI is opened —
and these defaults do **not** match Sonarr/Radarr's out-of-the-box expectations of
`tv-sonarr` / `radarr` either.

### 1.6 `.env` / `.env.example`

`grep -i 'categ' .env .env.example` → no output. No environment-level category variable.

### 1.7 Inventory (`ansible/inventory/hosts.ini`)

```ini
[the_host]
192.168.2.22 ansible_user=ansible media_drive_device=
```

No host-level or group-level category variable.

---


## 2. Per-occurrence rendering table (consolidated)

When `ansible-playbook -i ansible/inventory/hosts.ini ansible/playbooks/provision_host.yml`
is run against the current inventory, the two templates render as follows (only fields
that *could* have carried a category are shown — all are blank):

| Side | File rendered | Field that *should* carry the category tag | Actual rendered value | Verdict |
|------|---------------|---------------------------------------------|------------------------|---------|
| **Sonarr** | `/opt/mediastack/appdata/sonarr/config.xml` | (no XML field — Sonarr keeps it in `sonarr.db` not `config.xml`) | n/a | **No category provisioned**; Sonarr's *Download Clients → SABnzbd → Category* field is empty after first boot |
| **Radarr** | `/opt/mediastack/appdata/radarr/config.xml` | (same) | n/a | **No category provisioned** |
| **Recyclarr** | `/opt/mediastack/appdata/recyclarr/recyclarr.yml` | `sonarr[].download_clients[].category` (Recyclarr does not actually support this key; categories are *not* in Recyclarr's domain) | absent | **No category provisioned** (and Recyclarr is the wrong tool for this anyway — see §3) |
| **SABnzbd** | `/opt/mediastack/appdata/sabnzbd/sabnzbd.ini` | `[categories]` section | absent (`SABNZBD_API_KEY=""` at `provision_host.yml:483` confirms no pre-seed; first boot writes vanilla defaults) | **No category provisioned** |

---

## 3. Diff — *exactly* where Sonarr and Recyclarr diverge

The conventional way to state a category-drift bug is "side A says `tv_sonarr`, side B
says `tv-sonarr`" (underscore vs hyphen, or a typo). **That is not the bug here.** A
careful file-by-file comparison shows the divergence is **structural, not lexical**:

### 3.1 The literal diff

```
ansible/files/recyclarr/recyclarr.yml.j2          ansible/files/servarr/config.xml.j2
─────────────────────────────────────────────     ──────────────────────────────────────────
 sonarr:                                           <Config>
   - name: sonarr                                    <Port>{{ item.port }}</Port>
     base_url: http://sonarr:8989                    <BindAddress>*</BindAddress>
     api_key: {{ sonarr_key }}                       <ApiKey>{{ item.api_key }}</ApiKey>
     include:                                        <AuthenticationMethod>None</AuthenticationMethod>
       - template: sonarr-quality-definition-…       <UpdateMechanism>Docker</UpdateMechanism>
       - template: sonarr-v3-quality-profile-…     </Config>
       - template: sonarr-v3-custom-formats-…
              ^                                              ^
              │                                              │
              └─── NO download_clients: / categories:        └─── NO <Category> / <SabCategory>
                   block, NO sabnzbd reference at all             element, no SABnzbd reference
                                                                   at all
```

### 3.2 Categorised divergence

| Drift dimension | Sonarr side (`config.xml.j2`) | Recyclarr side (`recyclarr.yml.j2`) | Outcome |
|-----------------|-------------------------------|--------------------------------------|---------|
| Case (e.g. `Tv-Sonarr` vs `tv-sonarr`) | n/a — field absent | n/a — field absent | Cannot drift; nothing to compare |
| Typo (`tv-sonar` vs `tv-sonarr`) | n/a — field absent | n/a — field absent | Cannot drift |
| Missing block | **Missing `<DownloadClients>` / `<Category>` element** (Sonarr stores download-client config in its SQLite DB, not in `config.xml`, but neither path is templated) | **Missing `sonarr[].download_clients` / `media_management` block** | **Both blocks are missing on both sides** |
| Missing variable | No `sonarr_sabnzbd_category` (or analogous) Ansible variable anywhere in the repo | Same | Confirmed by exhaustive grep (§1.4) |
| Missing `download_client` entry on Sonarr | Sonarr has **no `<DownloadClients>` configuration provisioned at all** — the entire entry must be added through the Sonarr UI on first boot | Recyclarr cannot author Sonarr's download-client entry; it has no `download_client:` directive in any include template | **Sonarr's Download Client → SABnzbd link does not exist post-provision** |
| Missing category on SABnzbd | n/a | n/a | `provision_host.yml:483` sets `SABNZBD_API_KEY=""`; no `sabnzbd.ini` is templated; no category seeded |

### 3.3 The single failing invariant

> **For every download-client integration to function, there must exist exactly one
> string `C` such that:**
>
> 1. Sonarr's `Settings → Download Clients → SABnzbd → Category` equals `C`,
> 2. SABnzbd's `Config → Categories` contains a row whose name equals `C` (byte-for-byte),
> 3. (recommended) SABnzbd's category row maps to a folder under
>    `/data/usenet/` so that Sonarr's full-`/data` bind-mount can hardlink the
>    completed file across to `/data/media/tv/`.
>
> **The current state is that `C` is undefined on every side.** This satisfies
> `recyclarr sync` literally (Recyclarr only configures quality profiles and custom
> formats and successfully exits 0), while leaving Sonarr→SABnzbd routing broken —
> the symptom the upstream bug report describes.

[SPEC-GAP] The missing spec file `bug-sonarr-sabnzbd-sync.md` would presumably pin
the exact value of `C` (most likely `tv-sonarr` for Sonarr and `radarr` for Radarr,
matching the LinuxServer.io / TRaSH-Guides community convention). Task 3 must either
(a) recover that spec, or (b) adopt the community-conventional names as the de-facto
contract.

---


## 4. Recommendation — Single Source of Truth for Task 3

### 4.1 Proposed solution

Introduce **two new Ansible variables**, declared once in
`ansible/playbooks/provision_host.yml` under `vars:` (the only existing inventory
sink — there are no `group_vars/`, `host_vars/`, or roles):

```yaml
vars:
  # … existing vars …
  sonarr_sabnzbd_category: "tv-sonarr"      # SoT for Sonarr ↔ SABnzbd routing
  radarr_sabnzbd_category: "radarr"          # SoT for Radarr ↔ SABnzbd routing
```

Then drive **three** rendered artefacts from those two variables:

| Artefact | Where to template the variable |
|----------|--------------------------------|
| Sonarr's pre-seeded download-client entry | Either (a) extend `config.xml.j2` to also emit a minimal `<DownloadClientConfig>` section (Sonarr v3 honours a small subset in `config.xml`), or (b) add a new template e.g. `ansible/files/servarr/sonarr-downloadclients.json.j2` and `POST` it to Sonarr's API after the container is up. Option (b) is cleaner because Sonarr's full download-client config lives in `sonarr.db`, not `config.xml`. |
| SABnzbd's category row | Add a new `ansible/files/sabnzbd/sabnzbd.ini.j2` (or API-driven task) seeded with the same variable, so the SABnzbd `[categories]` section contains a row named `{{ sonarr_sabnzbd_category }}` pointing at `/data/usenet/{{ sonarr_sabnzbd_category }}/`. Also create that directory in `provision_host.yml`'s filesystem block. |
| Recyclarr | **Do not modify `recyclarr.yml.j2`.** Recyclarr does not own category routing (confirmed against the upstream config reference). Leaving Recyclarr out of category management is correct DDD: Recyclarr belongs to the *Maintenance* bounded context (TRaSH-Guides sync), not the *Acquisition ↔ Processing* boundary that owns categories. |

### 4.2 Justification against the Constitution

**Maxim 1 — Zero-Click Provisioning (Infrastructure-as-Code)**

> *"There will be no manual installation of dependencies. The entire system must be
> defined in declarative configuration (Ansible + Docker Compose)."*

The current state requires the operator to manually:

1. Open Sonarr's UI → Settings → Download Clients → Add → SABnzbd → fill in API key + category.
2. Open SABnzbd's UI → Config → Categories → add a row whose name matches step 1.
3. Repeat for Radarr.

That is **three** manual UI clicks per fresh provision, each capable of introducing
the very case/typo drift that breaks the integration. A single declarative Ansible
variable referenced from both rendering sites eliminates the manual step and makes
drift literally impossible (one variable cannot disagree with itself).


**Maxim "Infrastructure TDD Invariant"**

> [SPEC-GAP] This maxim is **not present verbatim** in `.ruler/CONSTITUTION.MD` as
> shipped in this worktree. The closest equivalents actually present are
> `molecule/default/tests/test_host_provision.py` (the Testinfra contract), the
> CONSTITUTION's overall "highly resilient … automated" mandate, and
> `AGENTS.md §3` on Idempotency. Interpreting the maxim in the spirit of those
> sources:
>
> *"Every production invariant must be expressible as a deterministic, executable
> test that fails before the fix and passes after."*

A single Ansible variable enables a one-line, deterministic Testinfra assertion of
the form:

```python
def test_sonarr_and_sabnzbd_agree_on_category(host):
    sonarr_cat   = grep_sonarr_db_for_sabnzbd_category(host)
    sabnzbd_cat  = grep_sabnzbd_ini_for_categories(host)
    expected     = "tv-sonarr"   # mirrors vars.sonarr_sabnzbd_category
    assert sonarr_cat == expected == sabnzbd_cat
```

Compared with the alternatives the test surface is minimal and unambiguous:

| Alternative SoT | Why rejected |
|-----------------|--------------|
| Hard-code `"tv-sonarr"` in three places | Violates DRY; restores the very drift surface this bug demonstrates; impossible to assert "they agree" with a single equality test. |
| Put the value in `.env` (e.g. `SONARR_SABNZBD_CATEGORY=tv-sonarr`) | `.env` is consumed by Docker Compose at container *runtime*, but Sonarr's category is stored in `sonarr.db` and is not read from env. The variable would have to be templated *into* a config file by Ansible anyway, so putting it in Ansible vars directly is one fewer indirection. |
| Put the value inside `recyclarr.yml.j2` | Recyclarr does not own this concern (see §1.2 and §4.1). Adding it there would be a layering violation: the *Maintenance* bounded context would be mutating the *Acquisition / Processing* contract. |
| Add a new `group_vars/the_host.yml` | Acceptable but heavier — it forces the creation of a `group_vars` directory that does not exist today. Sticking with the existing `vars:` block in `provision_host.yml` preserves the project's current zero-layer convention until / unless multiple plays start needing the value. |

### 4.3 Recommended variable names (concrete)

| Variable | Recommended value | Used by |
|----------|-------------------|---------|
| `sonarr_sabnzbd_category` | `"tv-sonarr"` | Sonarr download-client pre-seed task + SABnzbd `sabnzbd.ini.j2` `[categories]` block + filesystem task that creates `/opt/mediastack/data/usenet/tv-sonarr/` |
| `radarr_sabnzbd_category` | `"radarr"` | Radarr download-client pre-seed task + SABnzbd `sabnzbd.ini.j2` `[categories]` block + filesystem task that creates `/opt/mediastack/data/usenet/radarr/` |

Values mirror the LinuxServer.io / TRaSH-Guides community convention used in every
public reference compose for this stack; [SPEC-GAP] the missing spec file may
override these — Task 3 must reconcile.

---

## Appendix A — Grep evidence

```bash
# No "categ" tokens anywhere in any rendered artefact:
$ grep -rni 'categ' /home/melvin/.cline/worktrees/ebb2d/CineVault \
        --include='*.j2' --include='*.yml' --include='*.yaml' \
        --include='*.xml' --include='*.ini' --include='*.cfg'
# (empty)

# No group_vars / host_vars / defaults / roles directories:
$ find /home/melvin/.cline/worktrees/ebb2d/CineVault -type d \
        \( -name group_vars -o -name host_vars -o -name defaults \
           -o -name vars -o -name roles \)
# (empty)

# All Jinja2 templates inventoried:
$ find /home/melvin/.cline/worktrees/ebb2d/CineVault -name '*.j2'
ansible/files/homepage/widgets.yaml.j2
ansible/files/homepage/docker.yaml.j2
ansible/files/homepage/services.yaml.j2
ansible/files/servarr/config.xml.j2          ← inventoried §1.3
ansible/files/recyclarr/recyclarr.yml.j2     ← inventoried §1.2
docker-compose.yml.j2                         ← inventoried §1.5
```

## Appendix B — Files **not** modified

This analysis created exactly one file: this document
(`docs/analysis/sonarr-sabnzbd-category-drift.md`). No `.j2`, `.yml`, `.yaml`, `.xml`,
`.ini`, `.cfg`, or test file was edited or created.

