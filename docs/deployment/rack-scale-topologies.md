# Rack-Scale Topologies

[← Docs index](../README.md) · [Rack-scale deployment](rack-scale.md)

**[Star](#star-topology)** | **[Clos](#clos-topology)** | **[L2](#l2-topology)** | **[None](#none-topology)** | **[Changing the topology](#changing-the-topology)**

---

Use this page to pick a topology and write its keys in `rack-profile.yaml`.
Each section says how the nodes are cabled and routed. The install steps, the
rest of the profile and the checks are in [Rack-scale deployment](rack-scale.md).

## Star Topology

Switchless hub-and-spoke. One node (the hub) forwards traffic between all
others via point-to-point /30 links.

**When to use:** pilots, POC, switchless hardware (HPE B300 HGX), 3–8 nodes.

> [!Warning]
> Star is in the schema but has not been validated on hardware. Use Clos,
> L2 or none.

```
master1 ──/30── worker1 (hub) ──/30── worker2
master2 ──/30──┘     │
master3 ──/30────────┘
```

**How it works:**
- Each cable is its own /30 subnet — two usable IPs per link
- The hub sets `fabric_router: true` → gets `ip_forward=1` and iptables FORWARD
- Spokes route to the fabric supernet via the hub's cable-local IP
- Calico runs in VXLAN mode (node-to-node mesh enabled)

**Key fields:**

```yaml
network:
  topology: star
  calico_mode: vxlan
  fabric_prefix: 30

# On the hub node:
worker1:
  fabric_router: true
  fabric_nics:
    - nic: ens801f0
      fabric_ip: 10.201.1.2
      prefix: 30
      peer: master1             # the node at the other end

# On a spoke:
master1:
  fabric_nics:
    - nic: ens801f0
      fabric_ip: 10.201.1.1
      prefix: 30
      peer: worker1             # points to the hub
```

> [!Important]
> Both ends of a cable **must** share the same /30 subnet. The parser validates
> this — a mismatch is a hard error.

---

## Clos Topology

Leaf/spine switch fabric with native BGP peering. Nodes connect to ToR leaf
switches; Calico peers directly with each leaf.

**When to use:** production, full HA, maximum throughput, 10+ nodes, scale-out.

**How it works:**
- Nodes have 1–2 NICs, each attached to a leaf switch
- Per-node BGPPeer CRDs tell Calico to peer with the leaf's SVI IP
- Dual-homed nodes get ECMP (multipath hash across both uplinks)
- Calico runs in BGP mode (bird backend, node-to-node mesh OFF)

**Key fields:**

```yaml
network:
  topology: clos
  calico_mode: bgp
  fabric_prefix: 16
  leafs:
    - name: leaf-a
      asn: 65001
      peer_ip: 10.201.0.1
      fabric_subnet: 10.201.0.0/16
    - name: leaf-b
      asn: 65002
      peer_ip: 10.202.0.1
      fabric_subnet: 10.202.0.0/16
  bgp:
    cluster_asn: 65100

# Dual-homed worker:
worker1:
  fabric_nics:
    - nic: ens801f0
      fabric_ip: 10.201.0.10
      leaf: leaf-a
    - nic: ens801f1
      fabric_ip: 10.202.0.10
      leaf: leaf-b              # ECMP across both uplinks
```

`leaf:` is optional: each NIC's leaf is the one whose `fabric_subnet` holds
its `fabric_ip`. If you set it, it must name a defined leaf and agree with the
subnet. A `fabric_ip` in no leaf's subnet, or in two overlapping ones, is an
error. A NIC on a leaf with `fabric_subnet: TBD` must name the leaf.

---

## L2 Topology

Flat L2 fabric switch — all nodes on one broadcast domain, no BGP peering
with the switch. Simpler than Clos (no leaf/spine, no per-node BGPPeer CRDs)
but limited to a single switch domain.

**When to use:** single L2 switch connecting all nodes, no multi-rack spine.

**How it works:**
- All nodes share one L2 broadcast domain (single VLAN/subnet)
- Netplan assigns fabric addresses only — no routes needed (all on-link)
- No leafs, no hub, no peer declarations

**Calico mode options:**

| Mode | Backend | Encapsulation | MTU | Use when |
|------|---------|--------------|-----|----------|
| `bgp` (recommended) | bird | None (native) | full fabric MTU | Default for L2 — nodes exchange pod routes directly over the segment |
| `vxlan` | VXLAN | Always | fabric MTU - `network.vxlan_overhead` (50) | The switch drops traffic from IPs it did not assign (e.g. IP source guard), or you otherwise need an overlay |

With `calico_mode: bgp` on L2, Calico uses **node-to-node mesh** (all nodes peer with each other) instead of the Clos model (per-node ToR peering). BGP runs only between the nodes — the switch is never a peer, so no `BGPPeer` CRDs are generated and `ecmp_nodes` is empty. The mesh is one session per node pair, which is fine at rack scale; past roughly 100 nodes, move to Clos with ToR peering. No `leafs:` block needed.

```
   ┌────────────── L2 fabric switch (one VLAN, MTU 9000) ──────────────┐
   └─────────┬─────────────────────┬─────────────────────┬─────────────┘
             │                     │                     │
     master1 ens786f0np0   master2 ens786f0np0   worker1 ens786f0np0
       10.201.1.1/16          10.201.1.2/16          10.201.1.3/16

  routes:   none — 10.201.0.0/16 is on-link on every node
  pod CIDR: 10.244.x.0/24 via 10.201.1.x (learned from the Calico node mesh)
```

> [!Note]
> **One fabric NIC per node on the segment.** Two NICs on the same node in the
> same subnet give the kernel two connected routes to one prefix, and the
> parser rejects the profile as ambiguous. The generated netplan configures
> plain `ethernets:` only — host bonds are not generated, so L2 has no
> multi-uplink redundancy today. If you need dual uplinks, use Clos.

**Key fields:**

```yaml
network:
  topology: l2
  calico_mode: bgp         # or vxlan when the switch needs an overlay
  fabric_prefix: 16
  mtu: 9000
  control_plane_on_fabric: true
  bgp:
    cluster_asn: 65100     # only needed when calico_mode: bgp

# All nodes — single NIC, no leaf/peer:
master1:
  fabric_nics:
    - nic: ens786f0np0
      fabric_ip: 10.201.1.1
```

> [!Note]
> L2 rejects `leafs:`, `fabric_router:`, `peer:`, and `leaf:` on NICs, and
> every `fabric_ip` must be inside the one segment. The parser enforces these
> as hard errors.

---

## None Topology

No fabric network at all. `rack-profile.yaml` is used purely for inventory
generation, node labels (CPU family, GPU vendor/model), and GPU Operator
auto-enablement. All traffic runs on the management network.

**When to use:** existing network is sufficient, but you want rack-profile.yaml
for GPU operator auto-install, node labeling, and structured inventory — without
deploying fabric networking.

**How it works:**
- All nodes use `mgmt_ip` as their Kubernetes `ip`/`access_ip`
- No netplan files generated — fabric roles skip entirely
- Calico forced to VXLAN on the management network, at its MTU (`network.mtu`, 1500 by default) less `network.vxlan_overhead` (50 by default)
- The install stops if the NIC holding a node's `mgmt_ip` carries less than `network.mtu`: the installer does not configure that NIC. A node whose NIC MTU cannot be read is named in a warning and not checked
- GPU operator still auto-enables from `accelerator:` field
- `metallb_ip_range` auto-detection works (mgmt IPs are reachable)

**Key fields:**

```yaml
network:
  topology: none
  calico_mode: vxlan       # forced — bgp rejected by parser
  # mtu: 1500             # the management network's MTU; 1500 by default
  pod_cidr: 10.244.0.0/16
  service_cidr: 10.96.0.0/12

# Nodes — mgmt_ip only, NO fabric_nics:
master1:
  hostname: node-cp1
  mgmt_ip: 10.0.0.10
  roles: [kube_control_plane, etcd]

worker1:
  hostname: node-gpu1
  mgmt_ip: 10.0.0.30
  profile: gpu-b300-hgx       # GPU operator auto-enables
  roles: [kube_node]
```

> [!Important]
> `topology: none` rejects `fabric_nics`, `calico_mode: bgp`, `leafs:`, and
> `fabric_router:`. The parser enforces these as hard errors.

---

## Changing the topology

The topology of an installed cluster can't be changed in place. Re-running
`install` on a running cluster skips Kubespray, so Calico's mode (VXLAN to BGP)
never changes. Tear the cluster down and install it again. Teardown removes
Ceph too, so back up what you need first. For example, star to Clos:

1. Tear down: `./toolkit_manager.sh teardown infrastructure --env <env>`
2. Install the ToR leaf switches and cable the nodes to them
3. Edit `rack-profile.yaml`:
   - Change `topology: star` → `topology: clos`
   - Change `calico_mode: vxlan` → `calico_mode: bgp`
   - Change `fabric_prefix: 30` → `fabric_prefix: 16`
   - Remove `fabric_router: true` and `peer:` from nodes
   - Add `leafs:` definitions and `leaf:` on each fabric NIC
   - Add `bgp: cluster_asn:`
4. Install: `./toolkit_manager.sh install inference --env <env>`

---

## Next steps

- [Rack-scale deployment](rack-scale.md) — install steps, the rest of `rack-profile.yaml`, validation and troubleshooting
- [Node scaling](node-scaling.md#rack-scale) — add or remove a worker on Clos, L2 and `none` racks
