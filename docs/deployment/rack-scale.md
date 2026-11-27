# Rack-Scale Deployment

[← Docs index](../README.md)

**[Overview](#overview)** | **[Quick Start](#quick-start)** | **[rack-profile.yaml](#writing-rack-profileyaml)** | **[Topologies](rack-scale-topologies.md)** | **[GPU](#gpu-nodes)** | **[Validation](#validation)** | **[Troubleshooting](#troubleshooting)**

---

Deploy Toolkit Manager on a rack of servers joined by a dedicated high-speed
network (the *fabric*), with Ceph storage on that fabric and optional GPU
acceleration. You describe the hardware once, in `rack-profile.yaml`, and the
installer configures the network, the cluster and the storage from it.

## Overview

Rack-scale mode adds a dedicated high-speed fabric to the infrastructure layer. It is
**disabled by default** (`rack_scale_enabled: false`) — when off, all fabric
components are skipped and the stack behaves identically to a standard
deployment. When enabled, the installer reads `rack-profile.yaml` and
automatically configures:

- **Fabric NICs** — persistent IP addressing via netplan on every node
- **Hub forwarding** (star) or **ECMP + BGP** (Clos) — topology-appropriate routing
- **Ceph on fabric** — OSD traffic binds to the high-speed network
- **NVIDIA GPU operator** — auto-installs when an NVIDIA `accelerator:` is declared (no separate flag)
- **Node labels** — CPU family, GPU vendor/model/form applied to K8s nodes

Four topologies share the same `rack-profile.yaml` schema. Each has its own
section, with cabling and example keys, in [Rack-scale topologies](rack-scale-topologies.md):

| Topology | Use Case | Switching | Calico Mode |
|----------|----------|-----------|-------------|
| [**Star**](rack-scale-topologies.md#star-topology) | Pilots, POC, switchless (e.g. HPE B300 HGX). Not validated on hardware | None — direct cables | VXLAN |
| [**Clos**](rack-scale-topologies.md#clos-topology) | Production, full HA, max throughput | Leaf/spine ToR switches | BGP |
| [**L2**](rack-scale-topologies.md#l2-topology) | L2-only fabric switch, flat broadcast domain | Single L2 switch | VXLAN or BGP (node mesh) |
| [**None**](rack-scale-topologies.md#none-topology) | GPU-only, no fabric — inventory + labels only | N/A | VXLAN (forced) |

The fabric steps run before Kubespray, so the fabric is up when Kubernetes
installs. The order is in [Architecture: rack-scale order](../reference/architecture.md#rack-scale-order).

## Prerequisites

- All [standard Toolkit Manager prerequisites](../getting-started/prerequisites.md)
- **Ubuntu 22.04 or 24.04 LTS on every node:** the fabric is configured through
  netplan, so RHEL and Rocky Linux nodes are not supported for rack-scale, even
  though the base installer supports them. The fabric step stops before writing
  anything if a node has no netplan.
- **Hardware:** fabric NICs on all nodes (check with `ip link show`). Any link
  speed works; every fabric NIC and switch port must carry the profile's MTU
  (`network.mtu`, 9000 by default). With `topology: none`, the management NICs
  and switch must carry it instead, and it defaults to 1500.
  - Star: direct cables between hub and each node
  - Clos: cables to ToR leaf switches
- **Network plan:** fabric IP addresses, subnet layout, cable map
- **Storage (optional):** raw NVMe devices for Ceph OSDs (not the OS disk)
- **GPU (optional):** NVIDIA GPUs get the GPU Operator from the rack profile; Intel GPUs get the Intel GPU device plugin on any cluster ([Intel GPUs](install-platform.md))

### Node readiness

Check every node before deploying. Reused nodes are the most common cause of a
failed rack-scale install. On a fresh install the installer also checks every
node before Kubespray starts. It stops on time, disk, internet access, a
half-removed etcd and, with Ceph, the OSD disks, and warns on leftovers from
another cluster. See
[Node checks before install](../getting-started/prerequisites.md#node-checks-before-install).

- **Clean nodes:** start from a fresh OS install. A node that was part of
  another cluster can carry kubelet and etcd state, `/etc/kubernetes`, CNI
  configuration, an old `/etc/netplan/99-fabric.yaml` with its fabric
  addresses, and Ceph signatures on the storage disks. Re-image it, or clean
  that state first.
- **Fabric NICs left to the installer:** no other netplan file (for example a
  cloud-init entry) or saved NetworkManager profile may configure a fabric
  NIC, and a fabric NIC may not be in a bond, bridge or VRF. The install stops
  and names the NIC or the profile (see [Troubleshooting](#troubleshooting)).
  NetworkManager can keep the node's other NICs.
- **Storage disks:** the disks listed for Ceph must be empty, not mounted, and
  not the OS disk. NVMe device names can change across reboots, so check
  `lsblk` on each node right before deploying.
- **Healthy package state:** no half-installed or failed packages, for example
  DKMS modules that do not build against the running kernel.
- **GPU nodes:** the GPU operator installs the NVIDIA driver
  (`nvidia_gpu_operator_driver_enabled: true`) or uses a driver already
  installed on the host, which it detects. On HGX systems with a host driver,
  NVIDIA Fabric Manager must also be installed and running on the host.

---

## Quick Start

Run these steps on the node the installer runs from. The example env is named `rack`.

1. Get the code and install the host tools (`configure` asks before it changes anything):

   ```bash
   git clone https://github.com/intel/toolkit-manager.git
   cd toolkit-manager
   ./toolkit_manager.sh configure
   ```

2. Create the environment:

   ```bash
   ./toolkit_manager.sh init inference --env rack
   ```

3. Edit `env/rack/global_config.yaml`: set `rack_scale_enabled: true`, `metallb_ip_range` (free addresses on the management network, required unless `topology: none`), and your proxy settings if you use one.

4. Write the hardware profile, following [Writing rack-profile.yaml](#writing-rack-profileyaml):

   ```bash
   cp configs/defaults/rack-profile.yaml.example env/rack/rack-profile.yaml
   vim env/rack/rack-profile.yaml
   ```

5. Deploy. The installer checks the profile first and stops with a clear message on any mistake (see [Troubleshooting](#troubleshooting)):

   ```bash
   ./toolkit_manager.sh install inference --env rack
   ```

6. Validate. This runs the fabric checks in [Validation](#validation) along with the other layers' checks:

   ```bash
   ./toolkit_manager.sh validate inference --env rack
   ```

> [!Note]
> `rack-profile.yaml` replaces `nodes.yaml` for rack-scale. Leave `nodes.yaml`
> empty (or don't create it) — the fabric_inventory role generates the Kubespray
> inventory from your rack profile. Install stops if `nodes_control_plane` or
> `nodes_workers` is set, because those would overwrite that inventory.

> [!Important]
> **Ceph storage:** the OSD devices and the Ceph networks both come from the
> `storage` section of `rack-profile.yaml`; set only `storage_backend: ceph` in
> `global_config.yaml`. A device can be a kernel name (`nvme1n1`) or a full path
> such as `/dev/disk/by-id/...`. With `storage_backend: ceph`, install stops before Kubespray if the profile
> lists no devices, and install and teardown stop if `global_config.yaml` still sets a
> different `rook_ceph_devices`. Delete `rook_ceph_devices` from `global_config.yaml`.
> Teardown also stops when `rook_ceph_teardown_wipe_devices: true` asks for a disk wipe
> but the profile lists no devices.

---

## Writing rack-profile.yaml

Copy the example and edit for your hardware:

```bash
cp configs/defaults/rack-profile.yaml.example env/<env>/rack-profile.yaml
```

### Site

```yaml
site:
  name: my-datacenter       # identifier for logs and reports
```

### Network

```yaml
network:
  topology: clos
  calico_mode: bgp
  mtu: 9000
  control_plane_on_fabric: true
  # Clos also needs leafs and bgp: see Rack-scale topologies
```

| Key | Default | Notes |
|-----|---------|-------|
| `topology` | `clos` | `clos`, `l2`, `none` or `star` (star is not validated on hardware). Set it explicitly |
| `calico_mode` | `vxlan` | `bgp` on Clos, `bgp` or `vxlan` on L2, `vxlan` on star and `none`. Set it explicitly: a Clos fabric runs `bgp` |
| `pod_cidr` | `10.244.0.0/16` | Pod CIDR |
| `service_cidr` | `10.96.0.0/12` | Service CIDR |
| `mtu` | `9000` (`1500` with `none`) | Must match every fabric NIC and switch port (with `none`, the management NICs) |
| `vxlan_overhead` | `50` | Taken off `mtu` for Calico VXLAN |
| `fabric_prefix` | `16` | Prefix of a fabric NIC that sets no `prefix:` (star: `30`) |
| `netplan_renderer` | `networkd` | `networkd` works with or without NetworkManager on the node: netplan tells NetworkManager to leave the fabric NICs alone. `NetworkManager` only if it is enabled on every node |
| `control_plane_on_fabric` | `false` | `true` (recommended) gives control-plane nodes their fabric IP for kubelet and etcd; `false` keeps their `mgmt_ip` |

The keys each topology adds (`leafs`, `bgp`, `fabric_router`, `peer`) are in
[Rack-scale topologies](rack-scale-topologies.md).

### SSH Access

```yaml
access:
  ansible_user: ubuntu                          # default: ubuntu
  ansible_ssh_private_key_file: ~/.ssh/id_ed25519  # default: ~/.ssh/id_ed25519
```

Every node is reached over SSH at its `mgmt_ip`, the one the installer runs on included. Per-node overrides are supported — set `ansible_user` or
`ansible_ssh_private_key_file` directly on any node.

### Node Profiles (optional)

Define the node hardware once, reference from nodes via `profile:`. A profile can set `node_family`, `sku`, `accelerator` and `gpu_count`; the same keys can also be set directly on a node, and a node's own value wins:

```yaml
node_profiles:
  cpu-gnr-ap-6980P:
    node_family: cpu-gnr-ap
    sku: 6980P
  gpu-b300-hgx:
    node_family: cpu-gnr-sp
    sku: 6776P
    accelerator: nvidia-b300-hgx    # format: vendor-model[-form]
    gpu_count: 8
```

### Nodes

Nodes are grouped under racks. Each node needs:

```yaml
racks:
  rack-01:
    nodes:
      master1:
        hostname: node-cp1            # short hostname
        mgmt_ip: 10.0.0.10           # management network IP (SSH)
        local: true                   # set on ONE node — the Ansible bastion
        roles: [kube_control_plane, etcd, storage]
        fabric_nics:
          - nic: ens801f0             # NIC name from `ip link show`
            fabric_ip: 10.201.0.10   # fabric IP address
            # leaf: leaf-a           # clos, optional: the leaf whose fabric_subnet holds fabric_ip
            # prefix: 30             # optional on-link prefix (default network.fabric_prefix; star: /30)
            # peer: worker1          # star only: the node at the other end of this cable
```

| Field | Required | Notes |
|-------|----------|-------|
| `hostname` | no | The machine's short hostname, kept as `node_hostname` in the inventory and used for the netplan file name (default: the node's key). The Kubernetes node name is the node's key under `racks` (e.g. `master1`), and Kubespray sets the OS hostname to it |
| `mgmt_ip` | yes | SSH reachable from the installer host. Every node needs it, the `local: true` node included: it SSHs to itself |
| `roles` | yes | At least one of `kube_control_plane`, `etcd`, `kube_node`, `storage`. A `storage` node must also be `kube_node` or `kube_control_plane`: Ceph runs as pods |
| `local` | no | Marks the node the installer runs on. It is still reached over SSH; the flag tells the installer whether its own host is on the fabric |
| `fabric_nics` | star, Clos, L2 | The node's fabric NICs, each with `nic` and `fabric_ip` (and optional `prefix`, `peer`, `leaf`). The first one is the node's Kubernetes address. Not allowed with `none` |
| `fabric_router` | no | **Star only.** Exactly one node. The hub that forwards between spokes |
| `profile` | no | Reference to a `node_profiles` entry |
| `node_family`, `sku` | no | CPU family (`cpu-gnr-ap`, `cpu-gnr-sp`, `cpu-cwf`, `cpu-spr`) and SKU, applied as the `cpu-gen` / `cpu-sku` node labels |
| `accelerator`, `gpu_count` | no | GPU as `vendor-model[-form]` (vendor `nvidia`, `intel` or `amd`) and its count. Both together, and `node_family` with them; see [GPU Nodes](#gpu-nodes) |
| `ansible_user`, `ansible_ssh_private_key_file` | no | Per-node SSH overrides of `access` |

An unknown key is an error (`unknown field 'X' — typo?`).

### Storage

```yaml
storage:
  ceph_public_network: 10.201.0.0/16    # client → OSD traffic
  ceph_cluster_network: 10.201.0.0/16   # OSD → OSD replication

  nodes:                                 # the Ceph storage nodes and their OSD devices
    - name: master1                      # the node's key under racks
      devices: [nvme1n1]                 # raw block devices (NEVER the OS disk): nvme1n1 or /dev/disk/by-id/...
    - name: master2
      devices: [nvme1n1]
```

Ceph runs with host networking and binds to the addresses in
`ceph_public_network` and `ceph_cluster_network`, so NIC names can differ per
node. The parser checks that every `storage` node has a fabric IP in
`ceph_public_network` (and in `ceph_cluster_network` when set), and that its
node IP is in the public network: a Ceph mon binds to its node IP, and Rook can
place a mon on any storage node. The node IP is the first fabric NIC, or
`mgmt_ip` on a control-plane node when `control_plane_on_fabric` is false. With
topology `none` there is no fabric, so each storage node's `mgmt_ip` must be in
the Ceph networks.

---

## GPU Nodes

Declare GPU hardware in `node_profiles` and reference from nodes:

```yaml
node_profiles:
  gpu-b300-hgx:
    node_family: cpu-gnr-sp
    sku: 6776P
    accelerator: nvidia-b300-hgx    # vendor-model[-form]
    gpu_count: 8

racks:
  rack-01:
    nodes:
      gpu-worker:
        hostname: hpe690
        mgmt_ip: 10.0.0.30
        roles: [kube_node]
        profile: gpu-b300-hgx        # references the profile above
        fabric_nics:
          - nic: ens801f0
            fabric_ip: 10.201.0.30     # Clos: inside a leaf's fabric_subnet
```

**What happens automatically:**
- Parser detects `accelerator:` → sets `rack_scale_gpu_vendor=nvidia`
- `node_feature_discovery`, first in the platform layer, installs the cluster's one NFD (release `node-feature-discovery` in namespace `node-feature-discovery`). It does this on every cluster, rack-scale or not, with or without GPUs, and the inference layer's `nfd` component is left out of install, validate and teardown; `nfd_enabled: false` turns NFD off
- `nvidia_gpu_operator` role installs the NVIDIA GPU operator without the chart's bundled NFD (NVIDIA only; other vendors log a warning and get no stack from this role)
- Both are platform components: `teardown inference` keeps them, `teardown platform` removes the GPU operator and NFD, and with NFD the node labels it set. On OpenShift the GPU operator and `gpu_observability` are not installed for now
- Node labels applied: `gpu-vendor=nvidia`, `gpu-model=b300`, `gpu-form=hgx`, `gpu-count=8` (and `cpu-gen` / `cpu-sku` from `node_family` / `sku`)
- These labels describe the hardware for you and your tools. GPU model pods are placed by their `nvidia.com/gpu` request, which the GPU operator makes the node advertise

No separate flag is needed — describe the hardware, the stack figures out what
to install.

---

## Validation

```bash
./toolkit_manager.sh validate inference --env rack
```

The `fabric_validate` role checks (read-only; with `topology: none` only the node labels are re-applied):

| Check | Star | Clos | L2 | Failure means |
|-------|------|------|----|---------------|
| Fabric IP reachability from the installer host | ✓ | ✓ | ✓ | NIC not configured or cable disconnected |
| Each fabric NIC up, with carrier, `network.mtu` and its address | ✓ | ✓ | ✓ | Netplan not applied, cable out, or NIC misconfigured |
| Don't-fragment ping at the profile MTU (above 1500 only) | ✓ | ✓ | ✓ | A switch port or NIC carries a smaller MTU |
| Node-to-node ping | ✓ | ✓ | ✓ | Routing broken — check hub or BGP |
| Hub `ip_forward` = 1 | ✓ | | | Hub not forwarding — re-run `install infrastructure` |
| Hub `rp_filter` = 2 | ✓ | | | Reverse-path filtering blocking fabric traffic |
| Hub iptables FORWARD ACCEPT, and saved | ✓ | | | FORWARD chain dropping fabric packets |
| BIRD running | | ✓ | | Calico's BGP daemon not running |
| Routes learned over BGP (`proto bird`) | | ✓ | ✓ (`bgp`) | Leaf (Clos) or node mesh (L2) sessions down — check ASN/`peer_ip`, TCP 179 |
| ECMP hash policy = 1 (dual-homed nodes) | | ✓ | | Multipath hashing not enabled |

Quorum members (etcd/control-plane) fail hard if unreachable. Worker nodes warn
and continue. Every check is listed per node as `OK:` or `FAIL:`; any `FAIL` fails the run.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `rack_scale_enabled is true but rack-profile.yaml not found` | Missing profile | Copy `configs/defaults/rack-profile.yaml.example` to `env/<env>/rack-profile.yaml` |
| `a saved NetworkManager profile configures a fabric NIC` | A NetworkManager profile also configures a fabric NIC (checked before netplan apply) | Delete the named profile (`nmcli connection delete '<profile>'`, or remove the file if NetworkManager is not running) and re-run. NetworkManager can keep the node's other NICs |
| `the fabric NICs are not as ... sets them` | Checked after netplan apply and in validate: another netplan file (for example cloud-init) or NetworkManager profile also configures the NIC, an old address is left, or the NIC is in a bond, bridge or VRF | Remove or narrow that entry, delete the old address (`ip addr del`), run `netplan apply` on the node, and re-run. A NIC without carrier is left to the fabric checks in [Validation](#validation); routes are not compared |
| `rack_scale_enabled is true but metallb_ip_range is not set` | Missing VIP | Set `metallb_ip_range` in `global_config.yaml` to free management-subnet addresses (e.g. `172.18.168.240-172.18.168.250`), not a node's own IP |
| `metallb_ip_range ... overlaps the fabric subnet` | VIP range on the fabric | Move `metallb_ip_range` to free management-subnet addresses; fabric IPs are not reachable from outside the rack |
| Kubespray can't SSH to workers | Star hub not forwarding | Check hub: `sysctl net.ipv4.ip_forward` (must be 1), `iptables -S FORWARD` (must have ACCEPT rules) |
| `declares peer '<node>', but no NIC on '<node>' is in <subnet>` | /30 subnet mismatch on a star cable | Both ends of a cable need IPs in the same /30 block (e.g. `.1/30` and `.2/30`) |
| `duplicate fabric_ip` | Two nodes share an IP | Check `rack-profile.yaml` for collisions |
| `storage node ... has no fabric_ip in ceph_public_network` | Ceph networks don't match the storage nodes | Give each storage node a fabric IP in the Ceph networks, or fix `ceph_public_network` / `ceph_cluster_network` |
| `storage node ... node IP ... is outside ceph_public_network` | The node IP (first fabric NIC, or `mgmt_ip` on a control-plane node off the fabric) is on another network | List the NIC in `ceph_public_network` first; on a control-plane node set `control_plane_on_fabric: true` or move the `storage` role |
| `storage node ... mgmt_ip ... is outside ceph_..._network` | Topology `none`: the Ceph networks don't hold the management addresses | Set the Ceph networks to the management subnet, or leave them out |
| `fabric_ip ... is not within leafX's fabric_subnet` | IP and `leaf:` disagree | Fix the `fabric_ip`, or drop `leaf:` and let the parser derive it |
| `fabric_ip ... is outside the L2 segment ...` | L2 node addressed in another subnet | Put every fabric IP in the one L2 subnet |
| `missing required field 'mgmt_ip'` / `has no roles` | Incomplete node entry | Add `mgmt_ip` and at least one role to the node |
| `the nodes come from rack-profile.yaml, but nodes_control_plane ... also set` | `nodes.yaml` defines nodes on a rack-scale env | Remove `nodes_control_plane` and `nodes_workers` from `env/<env>/nodes.yaml`; the rack profile lists the nodes |
| Kubespray hangs behind proxy | Fabric CIDRs not in no_proxy | The installer injects them automatically; verify with `echo $no_proxy` |
| `unknown field 'X' — typo?` | Schema validation | Fix the field name and re-run — the parser catches typos as hard errors |
| `GPU operator not installing` | Missing `accelerator:`, or the vendor is not NVIDIA | Add `accelerator: nvidia-b300-hgx` (or similar) to the node or its profile |
| BGP sessions not Established (Clos) | Leaf switch misconfigured | Verify `peer_ip`, `asn`, and `fabric_subnet` match the switch config |
| `topology=l2 does not use leafs` | L2 profile has `leafs:` block | Remove the `leafs:` section — L2 is a flat broadcast domain |
| `topology=none ... has fabric_nics` | None profile has fabric NICs | Remove `fabric_nics` from all nodes — topology=none uses mgmt_ip only |
| `storage.nodes entry 'X' is not a node defined under racks` / `needs a non-empty devices list` | Storage section out of step with the racks | Use the node names from `racks`, and give each storage node its OSD devices |
| `storage_backend is ceph, but rack-profile.yaml lists no Ceph OSD devices` | Devices not in the profile (or still only in `global_config.yaml`) | Add `storage.nodes` with each storage node's devices to `rack-profile.yaml` |
| `rook_ceph_devices in global_config.yaml ... differs from storage.nodes` | Devices set in two places | Delete `rook_ceph_devices` from `global_config.yaml`; the rack profile is the only source |
| `rook_ceph_teardown_wipe_devices is true, but rack-profile.yaml lists no Ceph OSD devices` | Disk wipe asked for, devices gone from the profile | Add the devices back to `storage.nodes`, or set `rook_ceph_teardown_wipe_devices: false` and wipe the disks by hand |
| `topology=none ... calico_mode must be vxlan` | None + BGP | Change `calico_mode: vxlan` — no fabric to run BGP over |

---

## Reference

### Parser Output Artifacts

| File | Purpose |
|------|---------|
| `inventory/hosts.yaml` | Kubespray inventory with fabric NICs, CPU and GPU metadata |
| `inventory/metadata/k8s-net-calico.yml` | Calico CNI config (BGP or VXLAN) |
| `inventory/metadata/k8s-net-fabric.yml` | Rack metadata (site, topology, CIDRs) |
| `inventory/netplan/<hostname>.yaml` | Per-node fabric NIC config |
| `inventory/metadata/bgp-peers/<name>.yaml` | Per-node BGPPeer CRDs (Clos only) |
| `inventory/metadata/vars/ceph-storage.yml` | Ceph fabric network + OSD devices |
| `inventory/metadata/rack-scale-flags.env` | Shell-sourceable derived flags |

### Config Variables

| Variable | Default | Location | Purpose |
|----------|---------|----------|---------|
| `rack_scale_enabled` | `false` | `global_config.yaml` | Master gate for all fabric components |
| `metallb_ip_range` | (auto-detect) | `global_config.yaml` | **Required for rack-scale** (except `topology: none`, where auto-detection picks reachable management addresses). Free management-subnet addresses for LoadBalancer VIPs (e.g. `172.18.168.240-172.18.168.250`). Not a fabric address: auto-detection picks fabric IPs, which are unreachable from outside the rack, and install stops if the range overlaps a fabric subnet. Not a node's own IP: with more than one control-plane node, MetalLB can announce it from another node, which then answers ARP for that node's address. |
| `storage_backend` | `local-path` | `global_config.yaml` | Set to `ceph` for fabric-attached storage |
| `rack-profile.yaml` | (none) | `env/<env>/` | Hardware profile — see above |

---

## Next steps

- [Rack-scale topologies](rack-scale-topologies.md) — cabling, routing and keys for star, Clos, L2 and `none`
- [Node scaling](node-scaling.md#rack-scale) — add or remove a worker on a rack
- [Architecture: rack-scale order](../reference/architecture.md#rack-scale-order) — the order the fabric steps run in
