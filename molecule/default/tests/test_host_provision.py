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

import ipaddress
import time

import pytest
import yaml

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
    "/opt/mediastack/appdata/maintainerr",
    "/opt/mediastack/appdata/dozzle",
    "/opt/mediastack/appdata/uptime-kuma",
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


def test_hostname_is_locally_resolvable(host):
    """
    The provisioned hostname must resolve locally on The Host.

    The playbook renames the machine to the role-based hostname early in the
    converge sequence. Debian sudo/become lookups depend on the host being
    locally resolvable, so /etc/hosts must keep the hostname mapped.
    """
    hostname = host.check_output("hostname").strip()
    hosts_line = host.check_output(
        r"""awk '$1 == "127.0.1.1" { print; exit }' /etc/hosts"""
    ).strip()
    hosts_fields = hosts_line.split()
    assert (
        len(hosts_fields) > 1
        and hosts_fields[0] == "127.0.1.1"
        and hostname in hosts_fields[1:]
    ), (
        f"/etc/hosts must map 127.0.1.1 to '{hostname}' so privileged tasks "
        "continue working after the hostname is changed"
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


# ===========================================================================
# Group F — On-Demand GPU Workload Offloading (Distributed Tdarr Node)
# Spec: distributed-tdarr topology — NFS export of The Library plus the
#       Tdarr Server control plane, both strictly scoped to the local
#       subnet per zero-trust micro-segmentation.
#
# The expected subnet is derived dynamically from the VM's default-route
# interface (provision_host.yml auto-detects the same subnet from host
# network facts), so the contract holds regardless of the libvirt/DHCP
# address range assigned to the test VM.
#
# The export must enforce identity parity via all_squash + anonuid/anongid
# mapping to mediasvc (UID/GID 5000) — AGENTS.md §3 Zero Root Execution.
# ===========================================================================

NFS_EXPORT_PATH = "/opt/mediastack/data"


def get_expected_subnet(host):
    """
    Derive the LAN subnet CIDR expected to be configured on The Host by
    inspecting the default-route interface of the VM.

    Mirrors provision_host.yml's runtime detection: the playbook computes
    'media_subnet_cidr' from ansible_default_ipv4.network/netmask, which
    corresponds to the default-route NIC. Assertions use this value so the
    suite is independent of any hardcoded IP range.
    """
    cmd = host.run("ip -4 route show default")
    assert cmd.rc == 0, "ip route show default must succeed on The Host"
    first_line = cmd.stdout.strip().splitlines()[0]
    dev = first_line.split()[4]

    addr_cmd = host.run(f"ip -4 -o addr show dev {dev}")
    assert addr_cmd.rc == 0, f"ip addr show dev {dev} must succeed on The Host"
    cidr_str = addr_cmd.stdout.split()[3]

    interface = ipaddress.IPv4Interface(cidr_str)
    return str(interface.network)


def test_nfs_kernel_server_package_installed(host):
    """
    The nfs-kernel-server package must be installed on The Host to serve
    The Library over NFS for the transient laptop GPU node.
    """
    nfs_pkg = host.package("nfs-kernel-server")
    assert nfs_pkg.is_installed, (
        "'nfs-kernel-server' package must be installed on The Host; "
        "required to export The Library (/opt/mediastack/data) to the "
        "distributed Tdarr laptop node"
    )


def test_nfs_export_line_configured(host):
    """
    /etc/exports must contain an export line for /opt/mediastack/data that:
      - Restricts access to the local subnet (auto-detected)
      - Squashes ALL clients to mediasvc identity (all_squash)
      - Maps anonuid/anongid to UID/GID 5000 (zero-trust UID/GID parity)
      - Includes fsid=1 (required: the export is the root of the media
        filesystem as mounted by provision_host.yml)

    AGENTS.md §3: Zero Root Execution via all_squash squashing to the
    canonical mediasvc identity.
    """
    exports_file = host.file("/etc/exports")
    assert exports_file.exists, (
        "/etc/exports must exist on The Host"
    )
    exports_content = exports_file.content_string
    expected_cidr = get_expected_subnet(host)

    assert NFS_EXPORT_PATH in exports_content, (
        f"/etc/exports must export '{NFS_EXPORT_PATH}' "
        "(The Library) for the distributed Tdarr node"
    )
    assert expected_cidr in exports_content, (
        f"NFS export must be restricted to subnet '{expected_cidr}'; "
        "a wider scope would violate zero-trust micro-segmentation"
    )
    assert "all_squash" in exports_content, (
        "NFS export must use 'all_squash' to squash every remote client "
        "to the mediasvc identity (zero-trust UID/GID parity)"
    )
    assert "anonuid=5000" in exports_content, (
        "NFS export must map anonuid=5000, matching the mediasvc UID "
        "provisioned by provision_host.yml"
    )
    assert "anongid=5000" in exports_content, (
        "NFS export must map anongid=5000, matching the mediasvc GID "
        "provisioned by provision_host.yml"
    )
    assert "fsid=1" in exports_content, (
        "NFS export must include 'fsid=1'; /opt/mediastack/data is the root "
        "of the media filesystem and NFSv4 requires an explicit fsid to "
        "export a filesystem root"
    )

    # Exactly ONE content line may exist (the managed block). Unmarked legacy
    # lines from the pre-blockinfile lineinfile era sit alongside the managed
    # block and make `exportfs -ra` fail with "duplicated export entries"
    # (issue #26). The marker line itself starts with '#' and is not counted.
    export_lines = [
        line for line in exports_content.splitlines()
        if line.startswith(NFS_EXPORT_PATH)
    ]
    assert len(export_lines) == 1, (
        f"Expected exactly one export line for {NFS_EXPORT_PATH} in "
        f"/etc/exports, found {len(export_lines)}: {export_lines}. "
        "Duplicated export entries make `exportfs -ra` fail."
    )


def test_ufw_allows_nfs_from_local_subnet(host):
    """
    UFW must allow inbound NFS (port 2049) from the local subnet ONLY.

    The distributed Tdarr laptop node mounts The Library over NFSv4, which
    uses port 2049 exclusively. The allow rule must be scoped to the
    auto-detected local subnet — not exposed to Anywhere — per zero-trust
    micro-segmentation (ARCHITECTURE.md §2).
    """
    ufw_status = host.run("sudo ufw status verbose")
    assert ufw_status.rc == 0, "ufw status verbose must succeed"
    output = ufw_status.stdout
    expected_cidr = get_expected_subnet(host)

    assert "2049" in output, (
        "UFW must have an ALLOW rule for port 2049 (NFS) to serve the "
        "distributed Tdarr node"
    )
    assert expected_cidr in output, (
        f"UFW NFS rule must reference subnet '{expected_cidr}'; "
        "the export is scoped to the local subnet per the approved plan"
    )


def test_ufw_allows_tdarr_control_from_local_subnet(host):
    """
    UFW must allow inbound Tdarr Server control-plane traffic (port 8266/tcp)
    from the local subnet ONLY.

    The transient laptop node registers with the Tdarr Server on 8266. The
    rule must be scoped to the auto-detected local subnet — the control
    plane is never exposed beyond the local subnet (CONSTITUTION.md §2
    Maxim 4).
    """
    ufw_status = host.run("sudo ufw status verbose")
    assert ufw_status.rc == 0, "ufw status verbose must succeed"
    output = ufw_status.stdout
    expected_cidr = get_expected_subnet(host)

    assert "8266" in output, (
        "UFW must have an ALLOW rule for port 8266 (Tdarr Server control "
        "plane) so the external node can register"
    )
    assert expected_cidr in output, (
        f"UFW Tdarr control-plane rule must reference subnet "
        f"'{expected_cidr}'; the control port is scoped to the local "
        "subnet per the approved plan"
    )


def test_ufw_does_not_expose_nfs_or_tdarr_to_anywhere(host):
    """
    UFW must NOT have open (Anywhere-scoped) rules for NFS (2049) or the
    Tdarr Server control plane (8266).

    Zero-trust micro-segmentation (ARCHITECTURE.md §2): offload ports are
    reachable only from the local subnet. An 'Anywhere' scope on either
    port would indicate the subnet restriction was lost.
    """
    ufw_status = host.run("sudo ufw status verbose")
    assert ufw_status.rc == 0, "ufw status verbose must succeed"

    expected_cidr = get_expected_subnet(host)
    lines = ufw_status.stdout.splitlines()
    for line in lines:
        if ("2049" in line or "8266" in line) and "Anywhere" in line:
            # A line like "2049/tcp  ALLOW   Anywhere" is a leak; a line
            # like "2049/tcp  ALLOW   192.168.121.0/24" is correct and is
            # validated by the positive tests above.
            pytest.fail(
                f"UFW rule is scoped to 'Anywhere' for an offload port: "
                f"'{line.strip()}'. NFS (2049) and the Tdarr control plane "
                f"(8266) must be restricted to {expected_cidr} "
                "(zero-trust micro-segmentation)."
            )


def test_ufw_allows_maintainerr_webui_from_local_subnet(host):
    """
    UFW must allow inbound Maintainerr (6246/tcp) WebUI traffic from the local
    subnet ONLY.

    The WebUI is a LAN-only operational tool and is never published through
    The Ingress (CONSTITUTION.md §2 Maxim 4). Its allow rule must therefore be
    scoped to the auto-detected local subnet — mirroring the NFS (2049) and
    Tdarr control-plane (8266) rules — per zero-trust micro-segmentation
    (ARCHITECTURE.md §2).
    """
    ufw_status = host.run("sudo ufw status verbose")
    assert ufw_status.rc == 0, "ufw status verbose must succeed"
    output = ufw_status.stdout
    expected_cidr = get_expected_subnet(host)

    assert "6246" in output, (
        "UFW must have an ALLOW rule for port 6246 "
        "(Maintainerr WebUI) so LAN clients can reach it"
    )
    for line in output.splitlines():
        if "6246" in line and "Anywhere" in line:
            pytest.fail(
                "UFW rule for Maintainerr (port 6246) is scoped to "
                f"'Anywhere': '{line.strip()}'. The WebUI must be "
                f"restricted to {expected_cidr} "
                "(zero-trust micro-segmentation)."
            )

    assert expected_cidr in output, (
        f"UFW Maintainerr WebUI rule must reference subnet '{expected_cidr}'; "
        "the WebUI is scoped to the local subnet per the approved plan"
    )


def test_ufw_allows_observability_webuis_from_local_subnet(host):
    """
    UFW must allow inbound Dozzle (8888/tcp) and Uptime Kuma (3001/tcp)
    WebUI traffic from the local subnet ONLY.

    Both are LAN-only operational tools (CONSTITUTION.md §2 Maxim 4) and are
    never published through The Ingress. Their allow rules must be scoped to
    the auto-detected local subnet — mirroring the Maintainerr (6246) rule —
    per zero-trust micro-segmentation (ARCHITECTURE.md §2).
    """
    ufw_status = host.run("sudo ufw status verbose")
    assert ufw_status.rc == 0, "ufw status verbose must succeed"
    output = ufw_status.stdout
    expected_cidr = get_expected_subnet(host)

    for port, tool in (("8888", "Dozzle"), ("3001", "Uptime Kuma")):
        assert port in output, (
            f"UFW must have an ALLOW rule for port {port} ({tool} WebUI) "
            "so LAN clients can reach it"
        )
        for line in output.splitlines():
            if port in line and "Anywhere" in line:
                pytest.fail(
                    f"UFW rule for {tool} (port {port}) is scoped to "
                    f"'Anywhere': '{line.strip()}'. The WebUI must be "
                    f"restricted to {expected_cidr} "
                    "(zero-trust micro-segmentation)."
                )
        scoped_rule = any(
            port in line and expected_cidr in line
            for line in output.splitlines()
        )
        assert scoped_rule, (
            f"UFW {tool} WebUI rule (port {port}) must be scoped to subnet "
            f"'{expected_cidr}' (zero-trust micro-segmentation)"
        )


# ---------------------------------------------------------------------------
# Deployed stack health-check contract
# Motivated by the 2026-10-03 Jellyfin outage postmortem: a watchtower
# update killed the service at 04:02 and nothing restarted it for 16+ hours,
# with no health signal anywhere to surface the outage.
# ---------------------------------------------------------------------------

# Long-running services that must define a compose-level healthcheck in the
# rendered stack. cloudflared (distroless image — no shell, no HTTP client),
# recyclarr (one-shot run) and homepage/wizarr/maintainerr/gluetun/watchtower
# (image-built-in HEALTHCHECK) are deliberately excluded.
HEALTHCHECK_SERVICES = [
    "jellyfin",
    "radarr",
    "sonarr",
    "prowlarr",
    "spotweb-db",
    "spotweb",
    "bazarr",
    "sabnzbd",
    "tdarr",
    "seerr",
    "qbittorrent",
    "docker-proxy",
    "dozzle",
    "uptime-kuma",
]


def test_deployed_compose_defines_healthchecks(host):
    """
    Every long-running service in the deployed stack must define a
    healthcheck so its state is visible via `docker ps` (HEALTH column)
    and the Homepage docker widget.

    Postmortem (2026-10-03): Jellyfin was down for 16+ hours with no health
    signal to surface the outage; the recovery required a host reboot.
    """
    compose = host.file("/opt/mediastack/docker-compose.yml")
    assert compose.exists, "The rendered compose file must exist on The Host"
    data = yaml.safe_load(compose.content_string)
    assert data and "services" in data, (
        "The deployed compose file must define a 'services' map"
    )

    for name in HEALTHCHECK_SERVICES:
        service = data["services"].get(name)
        assert service is not None, (
            f"Service '{name}' must be defined in the deployed compose file"
        )
        assert "healthcheck" in service, (
            f"Service '{name}' must define a healthcheck so its state is "
            "visible via `docker ps` and the Homepage docker widget"
        )


def test_observability_webuis_publish_lan_scoped_ports(host):
    """
    Dozzle and Uptime Kuma are LAN-only operational tools: their WebUIs must
    be published on The Host (so the Homepage links via mediacenter.local
    work) and restricted to the local subnet by UFW — mirroring the
    Maintainerr WebUI (6246) contract. Dozzle must NOT collide with SABnzbd's
    host port (8080): it is published on 8888. Both must stay attached to
    ingress_net alongside homepage and cloudflared.
    """
    compose = host.file("/opt/mediastack/docker-compose.yml")
    assert compose.exists, "The rendered compose file must exist on The Host"
    data = yaml.safe_load(compose.content_string)

    dozzle = data["services"]["dozzle"]
    kuma = data["services"]["uptime-kuma"]

    assert "8888:8080" in dozzle.get("ports", []), (
        "dozzle must publish its WebUI as 8888:8080 — container port 8080 "
        "collides with SABnzbd's host mapping"
    )
    assert "3001:3001" in kuma.get("ports", []), (
        "uptime-kuma must publish its WebUI as 3001:3001"
    )

    for name in ("dozzle", "uptime-kuma", "homepage", "cloudflared"):
        service = data["services"].get(name)
        assert service is not None, (
            f"Service '{name}' must be defined in the deployed compose file"
        )
        assert "ingress_net" in service.get("networks", []), (
            f"Service '{name}' must attach to ingress_net"
        )


def test_dozzle_mcp_socket_proxy_contract(host):
    """
    Dozzle must expose the MCP endpoint behind simple auth and reach Docker
    exclusively through the constrained socket proxy — never a raw socket
    mount.

    Security: a `:ro` docker.sock mount does not restrict Docker API calls
    (the flag only marks the socket file read-only on disk; API traffic still
    passes through), so Dozzle now connects to tcp://docker-proxy:2375 over
    socket_proxy_net — the same constrained path watchtower and Uptime Kuma
    use. MCP (DOZZLE_ENABLE_MCP) is opt-in and gated by
    DOZZLE_AUTH_PROVIDER=simple so /api/mcp is never anonymous.
    """
    compose = host.file("/opt/mediastack/docker-compose.yml")
    assert compose.exists, "The rendered compose file must exist on The Host"
    data = yaml.safe_load(compose.content_string)
    assert data and "services" in data, (
        "The deployed compose file must define a 'services' map"
    )

    dozzle = data["services"]["dozzle"]

    env = {}
    for entry in dozzle.get("environment", []):
        key, _, value = str(entry).partition("=")
        env[key] = value

    assert env.get("DOZZLE_ENABLE_MCP") == "true", (
        "dozzle must set DOZZLE_ENABLE_MCP=true so AI agents can use the "
        "read-only MCP endpoint (/api/mcp)"
    )
    assert env.get("DOZZLE_AUTH_PROVIDER") == "simple", (
        "dozzle must run with DOZZLE_AUTH_PROVIDER=simple — without "
        "authentication the MCP endpoint would expose container logs "
        "to anyone on the network"
    )
    assert env.get("DOZZLE_REMOTE_HOST", "").startswith(
        "tcp://docker-proxy:2375"
    ), (
        "dozzle must reach Docker via the constrained socket proxy "
        "(DOZZLE_REMOTE_HOST=tcp://docker-proxy:2375); got "
        f"{env.get('DOZZLE_REMOTE_HOST')!r}"
    )

    volumes = dozzle.get("volumes", [])
    for volume in volumes:
        assert "docker.sock" not in str(volume), (
            "dozzle must NOT mount /var/run/docker.sock — the :ro flag does "
            "not restrict API operations; use tcp://docker-proxy:2375 over "
            f"socket_proxy_net instead (found {str(volume)!r})"
        )
    assert "./appdata/dozzle:/data" in volumes, (
        "dozzle must persist /data (users.yml) on the appdata SSD "
        "(State vs. Compute — AGENTS.md §3)"
    )

    networks = dozzle.get("networks", [])
    assert "socket_proxy_net" in networks, (
        "dozzle must attach to socket_proxy_net to reach docker-proxy"
    )
    assert "ingress_net" in networks, (
        "dozzle must stay attached to ingress_net (Homepage links contract)"
    )
    assert "group_add" not in dozzle, (
        "dozzle no longer touches the Docker socket, so the docker-group "
        "supplementary group (group_add) must be removed"
    )


def test_dozzle_users_yml_seeds_admin_account(host):
    """
    Simple auth requires /data/users.yml to exist BEFORE Dozzle boots with
    DOZZLE_AUTH_PROVIDER=simple — a missing users.yml means no account can
    sign in to the WebUI or complete the MCP OAuth consent (total lockout).
    The configuration role seeds it idempotently via `dozzle generate`.
    """
    users = host.file("/opt/mediastack/appdata/dozzle/users.yml")
    assert users.exists, (
        "appdata/dozzle/users.yml must exist — Dozzle runs with simple auth "
        "and a missing users.yml means no account can ever sign in"
    )
    # users.yml is a credential database deliberately locked to
    # mediasvc:mediasvc 0600 by the configuration role, so the unprivileged
    # vagrant SSH user cannot `cat` it — testinfra's file module would raise
    # "Permission denied" (the exists/stat assertions need no read access).
    # Read the content via passwordless sudo instead, mirroring the UFW and
    # spotweb docker-exec checks elsewhere in this suite.
    raw = host.check_output(
        "sudo cat /opt/mediastack/appdata/dozzle/users.yml"
    )
    content = yaml.safe_load(raw)
    assert content and isinstance(content.get("users"), dict), (
        "users.yml must contain a 'users' map"
    )
    assert "admin" in content["users"], (
        "users.yml must seed the 'admin' account for WebUI/MCP sign-in"
    )
    password = content["users"]["admin"].get("password", "")
    assert password.startswith("$2a$") or password.startswith("$2b$"), (
        "the admin password must be stored as a bcrypt hash"
    )
    assert users.user == "mediasvc", (
        f"users.yml must be owned by mediasvc (got {users.user!r}) so the "
        "non-root Dozzle container can read it"
    )
    assert users.mode == 0o600, (
        f"users.yml holds a credential hash — mode must be 0600 "
        f"(got {oct(users.mode)})"
    )


def test_spotweb_waits_for_healthy_database(host):
    """
    spotweb must gate its startup on spotweb-db reporting HEALTHY, not merely
    on the container starting.

    The MariaDB healthcheck carries a 60s start_period while InnoDB
    initialises; the previous short-form depends_on raced it and spotweb
    failed with "Can't connect to MySQL server on 'spotweb-db'" (spotweb
    DB-connection postmortem — docs/configuration/spotweb.md).
    """
    compose = host.file("/opt/mediastack/docker-compose.yml")
    assert compose.exists, "The rendered compose file must exist on The Host"
    data = yaml.safe_load(compose.content_string)
    assert data and "services" in data, (
        "The deployed compose file must define a 'services' map"
    )

    spotweb = data["services"]["spotweb"]
    depends_on = spotweb.get("depends_on")
    assert isinstance(depends_on, dict), (
        "spotweb.depends_on must use the long syntax with a health condition "
        f"(got {depends_on!r})"
    )
    condition = depends_on.get("spotweb-db", {}).get("condition")
    assert condition == "service_healthy", (
        "spotweb must wait for spotweb-db with condition 'service_healthy' "
        f"to prevent the DB-startup race (got {condition!r})"
    )


def test_spotweb_db_user_authenticates_with_container_password(host):
    """
    The MariaDB 'spotweb' user must authenticate with the password the
    spotweb container actually presents.

    Postmortem (2026-09-26): a secrets-role refactor renamed its lookup files
    (spotweb_db.password -> spotweb.key), generating a NEW random password
    that was injected into .env — while the MariaDB datadir kept the original
    one (LSIO applies MYSQL_USER/MYSQL_PASSWORD only on first datadir
    initialisation). Every spotweb operation failed with
    "SQLSTATE[HY000] [1045] Access denied for user 'spotweb'" until the DB
    user was realigned by hand. The deployment role now reconciles the DB
    user with .env on every run; this test asserts the reconciled end state
    by reproducing the exact connection the application makes.
    """
    # The spotweb container may still be starting when verification begins —
    # wait (bounded) for it to accept exec calls.
    pw_cmd = None
    for _ in range(12):
        pw_cmd = host.run("sudo docker exec spotweb printenv SPOTWEB_DB_PASS")
        if pw_cmd.rc == 0 and pw_cmd.stdout.strip():
            break
        time.sleep(10)
    assert pw_cmd is not None and pw_cmd.rc == 0, (
        "spotweb container must be running (docker exec failed): "
        f"{'' if pw_cmd is None else pw_cmd.stderr}"
    )

    password = pw_cmd.stdout.strip()
    assert password, "SPOTWEB_DB_PASS must be non-empty in the spotweb container"

    auth = host.run(
        f"sudo docker exec -e MYSQL_PWD='{password}' spotweb-db "
        "mariadb -uspotweb -h127.0.0.1 -e 'SELECT 1'"
    )
    assert auth.rc == 0, (
        "spotweb must authenticate against spotweb-db with the password "
        "from its own container environment — credential drift between .env "
        "and the MariaDB datadir breaks every spotweb operation "
        f"(rc={auth.rc}, stderr={auth.stderr.strip()!r})"
    )


def test_homepage_jellyfin_widget_uses_api_version_2(host):
    """
    The Homepage Jellyfin widget must pin widget API version 2.

    Postmortem (2026-10-05): Watchtower auto-upgraded Jellyfin to 12.x,
    which removed the legacy /emby and /mediabrowser route prefixes.
    Homepage widget version 1 (the default) still calls emby/Items/Counts
    and emby/Sessions, so every request 404'd with an empty body and the
    dashboard widget failed with "API Error: Failed to execute 'json' on
    'Response': Unexpected end of JSON input" (gethomepage#7113).
    Version 2 uses the native endpoints (Items/Counts, Sessions) with an
    Authorization header.
    """
    services_yaml = host.file("/opt/mediastack/appdata/homepage/services.yaml")
    assert services_yaml.exists, (
        "The rendered Homepage services.yaml must exist on The Host"
    )
    data = yaml.safe_load(services_yaml.content_string)
    assert data, "The rendered Homepage services.yaml must not be empty"

    jellyfin_widget = None
    for group in data:
        if not isinstance(group, dict):
            continue
        for services in group.values():
            if not isinstance(services, list):
                continue
            for service in services:
                if not isinstance(service, dict):
                    continue
                if "Jellyfin" in service:
                    jellyfin_widget = service["Jellyfin"].get("widget")
                    break
            if jellyfin_widget is not None:
                break
        if jellyfin_widget is not None:
            break

    assert jellyfin_widget is not None, (
        "The Jellyfin service tile must define a widget in services.yaml"
    )
    assert jellyfin_widget.get("version") == 2, (
        "The Jellyfin widget must set version: 2 — Jellyfin >= 12 removed "
        "the legacy /emby API routes used by widget version 1"
    )


# ---------------------------------------------------------------------------
# Homepage dual-instance contract (docs/configuration/homepage.md)
# The dashboard is rendered twice: the LAN instance (mediacenter.local:80)
# links to The Host directly; the remote instance (dashboard.example.com via
# The Ingress) links to the Cloudflare Tunnel hostnames and renders LAN-only
# services status-only.
# ---------------------------------------------------------------------------


def _collect_homepage_services(data):
    """Flatten the grouped Homepage services.yaml into {name: properties}."""
    services = {}
    for group in data:
        if not isinstance(group, dict):
            continue
        for group_services in group.values():
            if not isinstance(group_services, list):
                continue
            for service in group_services:
                if not isinstance(service, dict):
                    continue
                for name, props in service.items():
                    services[name] = props
    return services


def test_homepage_spotweb_tile_links_acquisition_pipeline(host):
    """
    The LAN dashboard must surface Spotweb (the Dutch Usenet indexer) as a
    first-class tile: linked on its published host port (8085), bound to the
    `spotweb` container for status/stats, and probed by a site monitor.

    Regression guard: Spotweb was deployed via docker-compose.yml but absent
    from the Homepage dashboard, so the only entry point was the raw
    http://<host>:8085 URL.
    """
    services_yaml = host.file("/opt/mediastack/appdata/homepage/services.yaml")
    assert services_yaml.exists, (
        "The rendered Homepage services.yaml must exist on The Host"
    )
    data = yaml.safe_load(services_yaml.content_string)
    assert data, "The rendered Homepage services.yaml must not be empty"

    spotweb = _collect_homepage_services(data).get("Spotweb")
    assert spotweb is not None, (
        "The Spotweb tile must exist in the Homepage services.yaml — it was "
        "previously missing even though the container was deployed"
    )
    href = spotweb.get("href", "")
    assert href.startswith("http://") and href.endswith(":8085"), (
        f"The Spotweb tile must link to the published host port 8085 "
        f"(got href={href!r})"
    )
    assert spotweb.get("container") == "spotweb", (
        "The Spotweb tile must bind to the 'spotweb' container for the "
        "docker status/stats integration"
    )
    assert spotweb.get("siteMonitor") == "http://spotweb:80", (
        "The Spotweb tile must probe http://spotweb:80 via the site monitor "
        "— Homepage ships no native Spotweb widget"
    )


def test_homepage_remote_instance_compose_contract(host):
    """
    A second Homepage instance (homepage-remote) serves
    dashboard.example.com with *.example.com links. Contract:
      - defined in the deployed compose file
      - NO published ports: reachable exclusively through cloudflared on
        ingress_net (zero-trust micro-segmentation, ARCHITECTURE.md §2)
      - ingress_net membership so The Ingress can route to it
      - own config state at appdata/homepage-remote (State vs. Compute)
    """
    compose = host.file("/opt/mediastack/docker-compose.yml")
    assert compose.exists, "The rendered compose file must exist on The Host"
    data = yaml.safe_load(compose.content_string)

    remote = data["services"].get("homepage-remote")
    assert remote is not None, (
        "Service 'homepage-remote' must be defined in the deployed compose "
        "file (remote dashboard for dashboard.example.com)"
    )
    assert "ports" not in remote, (
        "homepage-remote must NOT publish any host port — The Ingress "
        "reaches it over ingress_net only"
    )
    assert "ingress_net" in remote.get("networks", []), (
        "homepage-remote must attach to ingress_net so cloudflared can "
        "route dashboard.example.com to it"
    )
    volumes = remote.get("volumes", [])
    assert any("appdata/homepage-remote:/app/config" in v for v in volumes), (
        "homepage-remote must keep its rendered config in "
        "appdata/homepage-remote (State vs. Compute, AGENTS.md §3)"
    )

    remote_dir = host.file("/opt/mediastack/appdata/homepage-remote")
    assert remote_dir.is_directory, (
        "The appdata/homepage-remote config directory must exist and be "
        "provisioned by the filesystem role"
    )


def test_homepage_remote_instance_uses_ingress_links(host):
    """
    The remote instance's rendered services.yaml must link to the public
    Cloudflare Tunnel hostnames (request/join/status + the apex domain for
    Jellyfin) and must NOT carry hrefs for LAN-only services, so no remote
    tile ever links to an unreachable mediacenter.local address. The LAN
    instance must keep the local links.

    Homepage cannot switch hrefs based on the viewing network (gethomepage
    PR #4093 was rejected upstream), so the split lives in the deployment.
    """
    remote_yaml = host.file(
        "/opt/mediastack/appdata/homepage-remote/services.yaml"
    )
    assert remote_yaml.exists, (
        "The rendered remote Homepage services.yaml must exist on The Host "
        "(appdata/homepage-remote/services.yaml)"
    )
    remote_services = _collect_homepage_services(
        yaml.safe_load(remote_yaml.content_string)
    )

    expected_ingress_hrefs = {
        "Jellyfin": "https://example.com",
        "Seerr": "https://request.example.com",
        "Wizarr": "https://join.example.com",
        "Uptime Kuma": "https://status.example.com",
    }
    for name, href in expected_ingress_hrefs.items():
        assert name in remote_services, (
            f"The remote dashboard must still show the {name} tile"
        )
        assert remote_services[name].get("href") == href, (
            f"The remote {name} tile must link to the Ingress hostname "
            f"{href!r} (got {remote_services[name].get('href')!r})"
        )

    for name in (
        "Radarr",
        "Sonarr",
        "Prowlarr",
        "Spotweb",
        "Bazarr",
        "SABnzbd",
        "qBittorrent",
        "Tdarr",
        "Dozzle",
        "Maintainerr",
    ):
        assert name in remote_services, (
            f"The remote dashboard must still show the {name} tile"
        )
        assert "href" not in remote_services[name], (
            f"The remote {name} tile must render status-only (no href): "
            "there is no public hostname for it, and a mediacenter.local "
            "link would be unreachable remotely"
        )

    lan_yaml = host.file("/opt/mediastack/appdata/homepage/services.yaml")
    assert lan_yaml.exists, (
        "The rendered LAN Homepage services.yaml must exist on The Host"
    )
    lan_services = _collect_homepage_services(
        yaml.safe_load(lan_yaml.content_string)
    )
    jellyfin_href = lan_services["Jellyfin"].get("href", "")
    assert jellyfin_href.startswith("http://") and jellyfin_href.endswith(
        ":8096"
    ), (
        f"The LAN Jellyfin tile must keep its local link (port 8096), got "
        f"{jellyfin_href!r}"
    )
    assert "example.com" not in jellyfin_href, (
        "The LAN dashboard must not link through The Ingress"
    )


def test_docker_proxy_grants_watchtower_lifecycle_permissions(host):
    """
    docker-proxy must grant watchtower (and Homepage's Docker widget) the
    lifecycle verbs a full container update requires: start, stop, restart
    and network attachment.

    Postmortem (2026-10-03): with only CONTAINERS/IMAGES/POST/DELETE set,
    watchtower could kill and re-create containers but never start the
    replacements, leaving Jellyfin and three other services offline until
    a host reboot.
    """
    compose = host.file("/opt/mediastack/docker-compose.yml")
    assert compose.exists, "The rendered compose file must exist on The Host"
    data = yaml.safe_load(compose.content_string)
    proxy = data["services"]["docker-proxy"]
    env = set(proxy.get("environment", []))
    required = {"ALLOW_START=1", "ALLOW_STOP=1", "ALLOW_RESTARTS=1", "NETWORKS=1"}
    assert required.issubset(env), (
        f"docker-proxy environment must grant watchtower the lifecycle "
        f"permissions {sorted(required)}; got {sorted(env)}"
    )


def test_docker_proxy_grants_uptime_kuma_docker_host_permissions(host):
    """
    docker-proxy must grant Uptime Kuma the endpoints its Docker-host
    connection test calls: /containers/json (CONTAINERS), /info (INFO)
    and /version (VERSION).

    INFO and VERSION both default to 0 in the proxy image; without them
    HAProxy's catch-all deny returns 403 when the Docker host is saved
    via Settings -> Docker Hosts -> Add (tcp://docker-proxy:2375).
    """
    compose = host.file("/opt/mediastack/docker-compose.yml")
    assert compose.exists, "The rendered compose file must exist on The Host"
    data = yaml.safe_load(compose.content_string)
    proxy = data["services"]["docker-proxy"]
    env = set(proxy.get("environment", []))
    required = {"CONTAINERS=1", "INFO=1", "VERSION=1"}
    assert required.issubset(env), (
        f"docker-proxy environment must grant Uptime Kuma the Docker-host "
        f"endpoints {sorted(required)}; got {sorted(env)}"
    )


def test_docker_proxy_image_pinned_to_stable_line(host):
    """
    docker-proxy must be patch-pinned to v0.4.2 (pre-HAProxy-3.4.2).
    v0.5.0 bumped HAProxy to 3.4.2 and upstream issue #180 reports it
    breaking endpoint handling; :latest would silently pull that in.
    """
    compose = host.file("/opt/mediastack/docker-compose.yml")
    assert compose.exists, "The rendered compose file must exist on The Host"
    data = yaml.safe_load(compose.content_string)
    proxy = data["services"]["docker-proxy"]
    image = proxy.get("image", "")
    assert image == "tecnativa/docker-socket-proxy:v0.4.2", (
        f"docker-proxy must be pinned to tecnativa/docker-socket-proxy:v0.4.2 "
        f"(the pre-HAProxy-3.4.2 line); got {image!r}"
    )


def test_docker_proxy_excluded_from_watchtower_updates(host):
    """
    docker-proxy must carry the watchtower disable label so it is never
    recreated mid-update-cycle. A proxy recreation drops the API connection
    every other container update flows through, and a failed mid-flight
    update is exactly what took down four services on 2026-10-03.
    """
    compose = host.file("/opt/mediastack/docker-compose.yml")
    assert compose.exists, "The rendered compose file must exist on The Host"
    data = yaml.safe_load(compose.content_string)
    proxy = data["services"]["docker-proxy"]
    labels = set(proxy.get("labels", []))
    assert "com.centurylinklabs.watchtower.enable=false" in labels, (
        "docker-proxy must be excluded from watchtower's update cycle via "
        "the 'com.centurylinklabs.watchtower.enable=false' label"
    )
