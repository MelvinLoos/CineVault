#!/bin/bash
# =============================================================================
# run-tdarr-node.sh — On-Demand Transient GPU Node for Distributed Tdarr
#
# Ubiquitous Language (PRODUCT_SPECIFICATION.md §1):
#   The Host      : The Intel N100 Mini-PC running the Tdarr Server control plane.
#   The Library   : /opt/mediastack/data on The Host, exported via NFSv4.
#   The Node      : This transient laptop (AMD Radeon RX 7600M XT) joining the
#                   Tdarr cluster on demand for GPU work offloading.
#
# Zero Root Execution (AGENTS.md §3):
#   The Tdarr node container runs as PUID=5000 / PGID=5000 (mediasvc), matching
#   the all_squash,anonuid/anongid=5000 squashing enforced by The Host's NFS
#   export. No process runs as root inside the container.
#
# Idempotency (AGENTS.md §3):
#   Every action is guarded: mounts are skipped if already mounted, stale
#   containers are removed before launch, and teardown tolerates missing state.
#
# Usage:
#   sudo ./run-tdarr-node.sh --server-ip 192.168.2.22
#   sudo ./run-tdarr-node.sh --server-ip 192.168.2.22 --node-id AMD-Laptop-Node
#   sudo ./run-tdarr-node.sh --stop
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_SERVER_IP="192.168.2.22"
DEFAULT_NODE_ID="AMD-Laptop-Node"
DEFAULT_MOUNT_POINT="/mnt/n100_data"
NFS_EXPORT="/opt/mediastack/data"
NODE_IMAGE="ghcr.io/haveagitgat/tdarr_node:latest"
SCRATCH_DIR="/var/tmp/tdarr-node-cache"
CONTAINER_NAME="tdarr-node"

SERVER_IP=""
NODE_ID="${DEFAULT_NODE_ID}"
MOUNT_POINT="${DEFAULT_MOUNT_POINT}"
MODE="start"

# ---------------------------------------------------------------------------
# CLI parsing
# ---------------------------------------------------------------------------
usage() {
    cat <<EOF
Usage: $0 [--server-ip <ip>] [--node-id <id>] [--mount-point <path>] [--stop]

Options:
  --server-ip <ip>   IP address of The Host (N100). Auto-detects via mDNS
                     (n100.local) when omitted; falls back to ${DEFAULT_SERVER_IP}.
  --node-id <id>     Tdarr nodeID/nodeName (default: ${DEFAULT_NODE_ID}).
  --mount-point <p>  Local NFS mountpoint (default: ${DEFAULT_MOUNT_POINT}).
  --stop             Graceful teardown: stop/remove the container, unmount
                     the NFS share and remove the scratch cache.

Requires root (sudo). Idempotent — safe to re-run.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --server-ip)
            [[ $# -ge 2 ]] || { echo "ERROR: --server-ip requires a value" >&2; exit 1; }
            SERVER_IP="$2"; shift 2 ;;
        --node-id)
            [[ $# -ge 2 ]] || { echo "ERROR: --node-id requires a value" >&2; exit 1; }
            NODE_ID="$2"; shift 2 ;;
        --mount-point)
            [[ $# -ge 2 ]] || { echo "ERROR: --mount-point requires a value" >&2; exit 1; }
            MOUNT_POINT="$2"; shift 2 ;;
        --stop)
            MODE="stop"; shift ;;
        -h|--help)
            usage; exit 0 ;;
        *)
            echo "ERROR: unknown argument '$1'" >&2; usage >&2; exit 1 ;;
    esac
done

# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------
if [[ "${EUID}" -ne 0 ]]; then
    echo "ERROR: This script must run as root (sudo). NFS mounts and /dev/dri access require it." >&2
    exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
    echo "ERROR: 'docker' CLI not found on PATH. Install Docker Engine first." >&2
    exit 1
fi

if ! command -v mount.nfs >/dev/null 2>&1; then
    echo "ERROR: 'mount.nfs' not found. Install the NFS client package:" >&2
    echo "  Debian/Ubuntu: sudo apt install nfs-common" >&2
    echo "  Fedora/RHEL:   sudo dnf install nfs-utils" >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Resolve The Host IP: explicit flag > mDNS auto-detect (avahi on The Host) > default
# ---------------------------------------------------------------------------
resolve_server_ip() {
    if [[ -n "${SERVER_IP}" ]]; then
        echo "${SERVER_IP}"
        return
    fi
    if command -v getent >/dev/null 2>&1 && getent hosts n100.local >/dev/null 2>&1; then
        getent hosts n100.local | awk '{print $1}' | head -n 1
        return
    fi
    echo "${DEFAULT_SERVER_IP}"
}

# ---------------------------------------------------------------------------
# Teardown: --stop
# ---------------------------------------------------------------------------
do_stop() {
    echo "=== Tdarr Node Teardown ==="

    if docker ps -a --format '{{.Names}}' | grep -qx "${CONTAINER_NAME}"; then
        echo "Stopping container '${CONTAINER_NAME}' (graceful, 30s timeout)..."
        docker stop -t 30 "${CONTAINER_NAME}" >/dev/null || true
        echo "Removing container '${CONTAINER_NAME}'..."
        docker rm "${CONTAINER_NAME}" >/dev/null || true
    else
        echo "Container '${CONTAINER_NAME}' not present — nothing to stop."
    fi

    if mountpoint -q "${MOUNT_POINT}" 2>/dev/null; then
        echo "Unmounting NFS share at ${MOUNT_POINT}..."
        umount "${MOUNT_POINT}" || { echo "WARNING: unmount failed — is another process using the mount?" >&2; }
    else
        echo "Mount point ${MOUNT_POINT} not mounted — nothing to unmount."
    fi

    if [[ -d "${SCRATCH_DIR}" ]]; then
        echo "Removing scratch cache ${SCRATCH_DIR}..."
        rm -rf "${SCRATCH_DIR}"
    fi

    echo "Teardown complete. The Host's Tdarr queue is unaffected."
    exit 0
}

# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------
do_start() {
    SERVER_IP_RESOLVED="$(resolve_server_ip)"

    echo "=== Tdarr Transient GPU Node Startup ==="
    echo "The Host (server IP) : ${SERVER_IP_RESOLVED}"
    echo "Node ID               : ${NODE_ID}"
    echo "Mount point           : ${MOUNT_POINT}"
    echo "NFS export            : ${SERVER_IP_RESOLVED}:${NFS_EXPORT}"

    # 1. Mount The Library via NFSv4.2 (only port 2049 — no rpcbind/mountd).
    echo "Ensuring mount point ${MOUNT_POINT} exists..."
    mkdir -p "${MOUNT_POINT}"

    if mountpoint -q "${MOUNT_POINT}" 2>/dev/null; then
        echo "NFS share already mounted at ${MOUNT_POINT} — skipping mount."
    else
        echo "Mounting NFS share..."
        mount -t nfs -o vers=4.2,rw,soft,timeo=30,retrans=3 \
            "${SERVER_IP_RESOLVED}:${NFS_EXPORT}" "${MOUNT_POINT}"
        echo "Mounted."
    fi

    # 2. Laptop-local scratch for transcode intermediates (never crosses NFS).
    mkdir -p "${SCRATCH_DIR}"

    # 3. Clear stale state, then launch the node container (idempotent).
    if docker ps -a --format '{{.Names}}' | grep -qx "${CONTAINER_NAME}"; then
        echo "Removing stale container '${CONTAINER_NAME}'..."
        docker stop -t 30 "${CONTAINER_NAME}" >/dev/null 2>&1 || true
        docker rm "${CONTAINER_NAME}" >/dev/null || true
    fi

    echo "Launching Tdarr node container (AMD GPU passthrough)..."
    docker run -d --name "${CONTAINER_NAME}" \
        --device /dev/dri \
        --device /dev/kfd \
        --group-add video \
        --group-add render \
        -e PUID=5000 \
        -e PGID=5000 \
        -e serverIP="${SERVER_IP_RESOLVED}" \
        -e serverPort=8266 \
        -e nodeID="${NODE_ID}" \
        -e nodeName="${NODE_ID}" \
        -v "${MOUNT_POINT}:/data" \
        -v "${SCRATCH_DIR}:/temp" \
        "${NODE_IMAGE}"

    echo ""
    echo "=== Node started successfully ==="
    echo "Container : $(docker ps -q -f name=${CONTAINER_NAME})"
    echo ""
    echo "Next steps in the Tdarr Web UI (http://${SERVER_IP_RESOLVED}:8265):"
    echo "  1. Wait for node '${NODE_ID}' to appear under the Nodes tab."
    echo "  2. Allocate 1 GPU worker + 1 CPU worker to the node."
    echo "  3. Assign the AMD VAAPI plugin stack (do NOT use the host QSV stack)."
    echo "  4. Configure Path Translators (node-internal paths):"
    echo "       Server /data  ->  Node /data"
    echo "       Server /temp  ->  Node /temp"
    echo ""
    echo "To tear down later:  sudo $0 --stop"
}

# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------
if [[ "${MODE}" == "stop" ]]; then
    do_stop
else
    do_start
fi