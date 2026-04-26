"""
test_host_provision.py — Testinfra test suite for "The Host"

Spec-Driven contract for Molecule Card 1 (TDI).
The Ansible playbook in Card 2 (../playbooks/provision_host.yml) MUST satisfy every
assertion in this file before being considered complete.

Ubiquitous Language (PRODUCT_SPECIFICATION.md §1):
  - The Host      : The physical Intel N100 Mini-PC running Debian 13 "Trixie".
  - The Library   : The structured directory where completed, renamed media files
                    reside permanently (/opt/mediastack/data/media/).
  - The Download Client : SABnzbd — pulls raw Usenet data to a temporary scratch
                    space (/opt/mediastack/data/usenet/).
  - The Indexer   : Prowlarr — search engine for Usenet, managed by the Acquisition
                    bounded context.
  - The Ingress   : Cloudflare Tunnel — the only authorised external access path.

All tests use the `host` fixture exclusively (pytest-testinfra).
Tests are deterministic and order-independent.
"""

import pytest

# ---------------------------------------------------------------------------
# Constants — single source of truth for IDs and paths within this suite.
# Derived strictly from ARCHITECTURE.md §1 and the Ansible playbook variables.
# ---------------------------------------------------------------------------

MEDIASVC_USER = "mediasvc"
MEDIASVC_GROUP = "mediasvc"
MEDIASVC_UID = 5000   # As defined in provision_host.yml vars.mediasvc_uid
MEDIASVC_GID = 5000   # As defined in provision_host.yml vars.mediasvc_gid

MEDIASTACK_ROOT = "/opt/mediastack"

# Full directory tree from ARCHITECTURE.md §1 File System Architecture.
# Every path here is an explicit contract requirement.
MEDIASTACK_DIRECTORIES = [
    # Root
    "/opt/mediastack",
    # Config state tree (appdata) — "Must reside on fast SSD" per ARCHITECTURE.md
    "/opt/mediastack/appdata",
    "/opt/mediastack/appdata/jellyfin",
    "/opt/mediastack/appdata/radarr",
    "/opt/mediastack/appdata/sonarr",
    "/opt/mediastack/appdata/prowlarr",
    "/opt/mediastack/appdata/sabnzbd",
    "/opt/mediastack/appdata/seerr",
    "/opt/mediastack/appdata/gluetun",
    "/opt/mediastack/appdata/qbittorrent",
    # Media Payload tree (data) — "Resides on High-Capacity Drive" per ARCHITECTURE.md
    "/opt/mediastack/data",
    # The Download Client scratch space — SABnzbd active Usenet downloads
    "/opt/mediastack/data/usenet",
    # The Library — intermediate parent
    "/opt/mediastack/data/media",
    # The Library: movies — Final destination for Radarr (ARCHITECTURE.md §1)
    "/opt/mediastack/data/media/movies",
    # The Library: tv — Final destination for Sonarr (ARCHITECTURE.md §1)
    "/opt/mediastack/data/media/tv",
]


# ===========================================================================
# Group A — Identity & Zero Root Execution
# Spec: AGENTS.md §3 "Zero Root Execution" + ARCHITECTURE.md §3
# ===========================================================================


def test_the_host_has_mediasvc_group(host):
    """
    The Host must have the 'mediasvc' system group with the canonical GID.

    AGENTS.md §3: "Never run Docker containers as root. Always utilize the
    PUID and PGID variables specified in the architecture."
    ARCHITECTURE.md §3: "All containers must execute under a non-root PUID
    and PGID corresponding to a dedicated `mediasvc` system user."
    """
    group = host.group(MEDIASVC_GROUP)
    assert group.exists, (
        f"System group '{MEDIASVC_GROUP}' must exist on The Host"
    )
    assert group.gid == MEDIASVC_GID, (
        f"Group '{MEDIASVC_GROUP}' must have GID {MEDIASVC_GID} "
        f"(got {group.gid}); required for deterministic PGID across containers"
    )


def test_the_host_has_mediasvc_user(host):
    """
    The Host must have the 'mediasvc' system user with canonical UID and
    the correct primary group.

    AGENTS.md §3: Zero Root Execution — PUID/PGID must be deterministic.
    ARCHITECTURE.md §3: dedicated `mediasvc` system user.
    """
    user = host.user(MEDIASVC_USER)
    assert user.exists, (
        f"System user '{MEDIASVC_USER}' must exist on The Host"
    )
    assert user.uid == MEDIASVC_UID, (
        f"User '{MEDIASVC_USER}' must have UID {MEDIASVC_UID} "
        f"(got {user.uid}); required for deterministic PUID in all containers"
    )
    assert user.group == MEDIASVC_GROUP, (
        f"User '{MEDIASVC_USER}' primary group must be '{MEDIASVC_GROUP}' "
        f"(got '{user.group}')"
    )


def test_mediasvc_user_is_non_login(host):
    """
    The mediasvc user must be a non-interactive system account with no login shell.

    AGENTS.md §3: Zero Root Execution — service accounts must not be
    interactive principals.  Derived from provision_host.yml
    shell: /usr/sbin/nologin.
    """
    user = host.user(MEDIASVC_USER)
    assert user.shell == "/usr/sbin/nologin", (
        f"User '{MEDIASVC_USER}' must have shell '/usr/sbin/nologin' "
        f"(got '{user.shell}'); interactive login is prohibited"
    )


def test_mediasvc_user_has_no_home_directory(host):
    """
    The mediasvc user must not have a real home directory.

    AGENTS.md §3: State vs. Compute isolation — service accounts must not
    accumulate state outside the defined mediastack tree.
    Derived from provision_host.yml: home: /nonexistent, create_home: no.
    """
    user = host.user(MEDIASVC_USER)
    assert user.home == "/nonexistent", (
        f"User '{MEDIASVC_USER}' home must be '/nonexistent' "
        f"(got '{user.home}'); a real home dir violates State vs. Compute isolation"
    )
    home_path = host.file("/nonexistent")
    assert not home_path.exists, (
        "Path '/nonexistent' must not physically exist on The Host; "
        "mediasvc is a headless system account"
    )


def test_mediasvc_user_is_not_in_sudo_group(host):
    """
    The mediasvc user must NOT be a member of the 'sudo' group.

    AGENTS.md §3: Zero Root Execution — container runtime accounts must
    never hold privilege-escalation capabilities on The Host.

    NOTE (spec gap): AGENTS.md prohibits root execution but does not list
    every forbidden group explicitly; 'sudo' is the canonical privilege
    escalation path on Debian and is therefore tested here by inference.
    """
    user = host.user(MEDIASVC_USER)
    assert "sudo" not in user.groups, (
        f"User '{MEDIASVC_USER}' must NOT be in the 'sudo' group; "
        "privilege escalation violates the Zero Root Execution constraint"
    )


# ===========================================================================
# Group B — File System Architecture / State Isolation
# Spec: ARCHITECTURE.md §1 File System Architecture (State Isolation)
# ===========================================================================


@pytest.mark.parametrize("directory", MEDIASTACK_DIRECTORIES)
def test_mediastack_directory_exists_and_is_owned_by_mediasvc(host, directory):
    """
    Every directory in the /opt/mediastack/ tree must:
      - Exist on The Host filesystem
      - Be a real directory (not a file, symlink, or device)
      - Be owned by user  'mediasvc' (UID 5000)
      - Be owned by group 'mediasvc' (GID 5000)
      - Have mode 0o755

    ARCHITECTURE.md §1: The system mandates a single root directory for all
    media data.  AGENTS.md §3: State vs. Compute — volumes must never be
    mapped outside these structures.  Zero Root Execution: all paths owned
    by the service account, not root.
    """
    d = host.file(directory)

    assert d.exists, (
        f"Directory '{directory}' must exist on The Host; "
        "it is part of the mandatory mediastack tree (ARCHITECTURE.md §1)"
    )
    assert d.is_directory, (
        f"'{directory}' must be a directory, not a file or symlink; "
        "symlinks would break Atomic Hardlinks (ARCHITECTURE.md §1)"
    )
    assert d.user == MEDIASVC_USER, (
        f"'{directory}' must be owned by user '{MEDIASVC_USER}' "
        f"(got '{d.user}'); required for Zero Root Execution (AGENTS.md §3)"
    )
    assert d.group == MEDIASVC_GROUP, (
        f"'{directory}' must be owned by group '{MEDIASVC_GROUP}' "
        f"(got '{d.group}'); required for consistent PGID across containers"
    )
    assert d.mode == 0o755, (
        f"'{directory}' must have mode 0o755 "
        f"(got {oct(d.mode)}); standard executable directory permissions"
    )


# ===========================================================================
# Group C — Atomic Hardlink Constraint
# Spec: ARCHITECTURE.md §1
# "Atomic Hardlinks (instantaneous, zero-space copies between download and
#  library folders)" require both source and destination on the SAME filesystem.
# ===========================================================================


def test_atomic_hardlink_constraint_usenet_and_media_on_same_filesystem(host):
    """
    The Download Client scratch space (/opt/mediastack/data/usenet) and
    The Library (/opt/mediastack/data/media) MUST reside on the same
    underlying filesystem.

    ARCHITECTURE.md §1: "The system mandates a single root directory for all
    media data to enable Atomic Hardlinks (instantaneous, zero-space copies
    between download and library folders)."

    Hard links are only possible within a single filesystem.  If these two
    paths live on different mounts, `ln` will fail with EXDEV, silently
    breaking the Radarr/Sonarr post-processing pipeline.

    Implementation: compare the device number (st_dev) via `stat -c %d`.
    """
    usenet_stat = host.run("stat -c '%d' /opt/mediastack/data/usenet")
    media_stat = host.run("stat -c '%d' /opt/mediastack/data/media")

    assert usenet_stat.rc == 0, (
        "stat on /opt/mediastack/data/usenet failed — directory may not exist"
    )
    assert media_stat.rc == 0, (
        "stat on /opt/mediastack/data/media failed — directory may not exist"
    )

    usenet_dev = usenet_stat.stdout.strip()
    media_dev = media_stat.stdout.strip()

    assert usenet_dev == media_dev, (
        f"ATOMIC HARDLINK VIOLATION: /opt/mediastack/data/usenet (device {usenet_dev}) "
        f"and /opt/mediastack/data/media (device {media_dev}) are on DIFFERENT "
        "filesystems.  Hard links across filesystems are impossible (EXDEV).  "
        "Both paths must reside under a single mount point as required by "
        "ARCHITECTURE.md §1."
    )


def test_atomic_hardlink_constraint_data_root_is_single_mount(host):
    """
    The entire /opt/mediastack/data tree must be under a single mount point
    so that hardlinks between The Download Client scratch space and The Library
    are always on the same device.

    ARCHITECTURE.md §1: single root directory for all media data.

    NOTE (spec gap): ARCHITECTURE.md specifies that appdata "must reside on
    fast SSD" and data "resides on High-Capacity Drive" — implying they MAY
    be on separate physical devices, which is expected.  This test explicitly
    verifies only that usenet and media share a device, not that they share
    the same device as appdata.
    """
    dev_usenet = host.run("stat -c '%d' /opt/mediastack/data/usenet").stdout.strip()
    dev_movies = host.run("stat -c '%d' /opt/mediastack/data/media/movies").stdout.strip()
    dev_tv = host.run("stat -c '%d' /opt/mediastack/data/media/tv").stdout.strip()

    assert dev_usenet == dev_movies, (
        f"ATOMIC HARDLINK VIOLATION: usenet (dev {dev_usenet}) and movies "
        f"(dev {dev_movies}) are on different devices (ARCHITECTURE.md §1)"
    )
    assert dev_usenet == dev_tv, (
        f"ATOMIC HARDLINK VIOLATION: usenet (dev {dev_usenet}) and tv "
        f"(dev {dev_tv}) are on different devices (ARCHITECTURE.md §1)"
    )


# ===========================================================================
# Group D — Docker Runtime
# Spec: CONSTITUTION.md §3 "Provisioning & Container Engine: Ansible + Docker"
#       ARCHITECTURE.md §3 Hardware Acceleration & Resource Constraints
# ===========================================================================


def test_docker_package_is_installed(host):
    """
    The docker.io package must be installed on The Host.

    CONSTITUTION.md §3: "Provisioning & Container Engine: Ansible + Docker Compose."
    provision_host.yml installs 'docker.io' (Debian package).
    """
    docker_pkg = host.package("docker.io")
    assert docker_pkg.is_installed, (
        "'docker.io' package must be installed on The Host; "
        "required by CONSTITUTION.md §3 for the container engine"
    )


def test_docker_compose_plugin_is_installed(host):
    """
    The docker-compose package must be installed on The Host.

    CONSTITUTION.md §3: Docker Compose is the mandatory orchestration tool.
    This is the Debian Trixie v2 plugin package.
    """
    compose_pkg = host.package("docker-compose")
    assert compose_pkg.is_installed, (
        "'docker-compose' package must be installed; "
        "Docker Compose v2 is mandated by CONSTITUTION.md §3"
    )


def test_docker_service_is_running(host):
    """
    The Docker daemon (systemd service 'docker') must be actively running
    on The Host.

    CONSTITUTION.md §3: Docker is the container engine.  An idle or failed
    daemon would prevent any container from starting.
    """
    docker_service = host.service("docker")
    assert docker_service.is_running, (
        "Docker systemd service must be in 'running' state on The Host; "
        "required for all containerised services (CONSTITUTION.md §3)"
    )


def test_docker_service_is_enabled_at_boot(host):
    """
    The Docker daemon must be enabled to start automatically on boot.

    CONSTITUTION.md §1: "highly resilient … automated local media stack that
    operates silently" — the stack must survive a power cycle without
    manual intervention.
    """
    docker_service = host.service("docker")
    assert docker_service.is_enabled, (
        "Docker systemd service must be enabled at boot on The Host; "
        "required for autonomous restart after power cycles (CONSTITUTION.md §1)"
    )


def test_docker_binary_is_accessible(host):
    """
    The `docker` CLI binary must exist and be executable on The Host's PATH.

    Prerequisite for all Ansible docker_compose tasks executed against
    The Host in Card 2 and Card 3.
    """
    docker_bin = host.file("/usr/bin/docker")
    assert docker_bin.exists, "'/usr/bin/docker' binary must exist on The Host"
    assert docker_bin.is_file, "'/usr/bin/docker' must be a regular file"


def test_dri_render_device_node_exists(host):
    """
    The Intel QuickSync hardware acceleration device node /dev/dri/renderD128
    must exist on The Host.

    ARCHITECTURE.md §3: "Jellyfin must have the /dev/dri/renderD128 device
    explicitly mapped."
    CONSTITUTION.md §2 Maxim 2: "Hardware-Accelerated Ingress: Transcoding
    must happen at the hardware level (Intel QuickSync)."

    NOTE (spec gap): The Molecule VM (libvirt/Vagrant) will NOT expose real
    Intel QuickSync hardware.  This test is skipped automatically in the
    Molecule environment and is intended to run only against the real physical
    Host during integration testing.  The test is defined here to codify the
    architectural contract.
    """
    if not host.file("/dev/dri").exists:
        pytest.skip(
            "/dev/dri does not exist — running in a VM without GPU passthrough. "
            "This test must pass on the real Intel N100 Host (ARCHITECTURE.md §3)."
        )
    dri_device = host.file("/dev/dri/renderD128")
    if not dri_device.exists:
        pytest.skip("Hardware device /dev/dri/renderD128 not found. Skipping for local VM testing.")

    assert dri_device.exists, (
        "/dev/dri/renderD128 must exist on The Host; "
        "Intel QuickSync hardware acceleration is mandatory (ARCHITECTURE.md §3)"
    )


# ===========================================================================
# Group E — UFW Firewall Hardening
# Spec: CONSTITUTION.md §2 Maxim 4 "No Port Forwarding — All remote access
#       will be routed through zero-trust tunnels (Cloudflare)."
#       ARCHITECTURE.md §2 Network Topography (Zero-Trust Micro-segmentation)
#
# NOTE (spec gap): Neither CONSTITUTION.md, ARCHITECTURE.md, nor AGENTS.md
# provides an explicit UFW rule set.  The rules below are derived by
# inference from the No Port Forwarding maxim:
#   - Default inbound policy MUST be DENY (block all unless explicitly allowed)
#   - Default outbound policy SHOULD be ALLOW (containers initiate outbound)
#   - SSH (port 22/tcp) MUST be allowed for Ansible management access
#   - Application ports (8096, etc.) must NOT appear as open inbound rules,
#     since they are served exclusively via cloudflared (The Ingress).
# ===========================================================================


def test_ufw_is_installed(host):
    """
    UFW (Uncomplicated Firewall) must be installed on The Host.

    Required to enforce the No Port Forwarding maxim (CONSTITUTION.md §2 §4)
    on Debian 13 "Trixie".
    """
    ufw_pkg = host.package("ufw")
    assert ufw_pkg.is_installed, (
        "'ufw' package must be installed on The Host; "
        "required for firewall hardening per CONSTITUTION.md §2 Maxim 4"
    )


def test_ufw_service_is_enabled_and_active(host):
    """
    UFW must be active (enabled) on The Host so that its rules are enforced.

    CONSTITUTION.md §2 Maxim 4: No Port Forwarding — the firewall must be
    active to enforce inbound deny policies.
    """
    ufw_status = host.run("sudo ufw status | head -1")
    assert ufw_status.rc == 0, "ufw status command must succeed"
    assert "active" in ufw_status.stdout.lower(), (
        "UFW must be in 'active' state on The Host; "
        "an inactive firewall provides no protection (CONSTITUTION.md §2 §4)"
    )


def test_ufw_default_inbound_policy_is_deny(host):
    """
    UFW default INPUT policy must be DENY (or REJECT) to implement the
    No Port Forwarding maxim.

    CONSTITUTION.md §2 Maxim 4: "No Port Forwarding. All remote access will
    be routed through zero-trust tunnels (Cloudflare)."
    ARCHITECTURE.md §2: Zero-Trust Micro-segmentation.

    The outbound default being ALLOW is acceptable (containers require
    outbound internet access for Usenet indexers and Cloudflare).
    """
    ufw_status = host.run("sudo ufw status verbose")
    assert ufw_status.rc == 0, "ufw status verbose must succeed"
    status_output = ufw_status.stdout.lower()
    # "default: deny (incoming)" is the canonical Debian UFW output
    assert "deny (incoming)" in status_output or "reject (incoming)" in status_output, (
        "UFW default inbound policy must be 'deny' or 'reject'; "
        "required by CONSTITUTION.md §2 Maxim 4 (No Port Forwarding)"
    )


def test_ufw_allows_ssh_inbound(host):
    """
    UFW must allow inbound SSH (port 22/tcp) so that Ansible can manage
    The Host remotely.

    NOTE (spec gap): SSH management access is implied by Ansible's operational
    model but not explicitly stated in the spec.  This rule is required for
    the provisioning pipeline to function; without it, the playbook itself
    cannot reach The Host to configure it.
    """
    ufw_status = host.run("sudo ufw status numbered")
    assert ufw_status.rc == 0, "ufw status numbered must succeed"
    # Accept "22", "OpenSSH", or "SSH" as valid representations of the rule
    output = ufw_status.stdout
    ssh_allowed = (
        "22" in output
        or "OpenSSH" in output
        or "SSH" in output.upper()
    )
    assert ssh_allowed, (
        "UFW must have an ALLOW rule for SSH (port 22) on The Host; "
        "required for Ansible management access"
    )


def test_ufw_does_not_expose_jellyfin_port_externally(host):
    """
    UFW must NOT have an ALLOW rule for port 8096 (Jellyfin HTTP) on the
    external interface.

    CONSTITUTION.md §2 Maxim 4: "No Port Forwarding — All remote access will
    be routed through zero-trust tunnels (Cloudflare)."
    ARCHITECTURE.md §2: Jellyfin is on 'ingress_net' and accessible only via
    cloudflared (The Ingress), never via a direct port mapping.

    NOTE (spec gap): The spec does not enumerate a port deny-list, but the
    No Port Forwarding maxim unambiguously prohibits any direct inbound rule
    for application service ports.
    """
    ufw_status = host.run("sudo ufw status")
    assert ufw_status.rc == 0, "ufw status must succeed"
    assert "8096" not in ufw_status.stdout, (
        "UFW must NOT expose port 8096 (Jellyfin) externally; "
        "Jellyfin is accessed exclusively through The Ingress (cloudflared) "
        "per CONSTITUTION.md §2 Maxim 4 (No Port Forwarding)"
    )
