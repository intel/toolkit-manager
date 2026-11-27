# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
"""What the RDMA read-back (roles/fabric_rdma/files/rdma_readback.py) means.

    {{ readbacks | rdma_readback_evaluate(expected, settings) }}
    {{ record | rdma_bw_pairs }}
    {{ ib_write_bw_output | rdma_bw_gbps }}
    {{ before | rdma_counter_deltas(after, priority) }}

readbacks: {host: read-back}. expected: {host: {"nics": node_rdma_nics, "mgmt_ip": ...}}.
settings: {"dscp", "priority", "pfc", "ecn"} from network.rdma.
"""

import ipaddress
import re

# One counter family each: retransmit causes, ECN-marked packets, PFC frames.
LOSS = re.compile(r"out_of_sequence|seq_err", re.I)
ECN = re.compile(r"ecn", re.I)
NOT_PFC_FRAMES = re.compile(r"duration|transition|xon", re.I)
QP_FAILED = re.compile(r"create .*QP", re.I)


def _pcie_gbps(pcie):
    speed, width = pcie.get("speed_gts"), pcie.get("width")
    if not speed or not width:
        return None
    # 8b/10b up to 5 GT/s, 128b/130b from 8 GT/s
    return round(speed * width * (128 / 130 if speed >= 8 else 0.8))


def _nic_problems(host, nic, want, got, mgmt_ip, settings):
    """(errors, warnings, record) for one RDMA NIC."""
    where = "%s %s" % (host, nic)
    mode = "shared" if want.get("shared") else "dedicated" if want.get("rdma_ip") else "site"
    if not got or not got.get("exists"):
        return ["%s: no such NIC" % where], [], None
    errors, warnings = [], []
    ports = got.get("rdma") or []
    addrs = [a.split("/")[0] for a in got.get("addrs", [])]
    if not ports:
        errors.append("%s: has no RDMA device (driver %s: is its RDMA driver loaded?)" % (where, got.get("driver")))
    elif any(p.get("link_layer") == "InfiniBand" for p in ports):
        errors.append("%s: is an InfiniBand port; rack-scale RDMA is RoCE v2 on Ethernet" % where)
    if mgmt_ip and mgmt_ip in addrs:
        errors.append("%s: carries the management address %s; RDMA does not run on the management NIC"
                      % (where, mgmt_ip))
    if not got.get("admin_up"):
        errors.append("%s: is down" % where)
    elif not got.get("carrier"):
        errors.append("%s: has no link" % where)
    elif ports and not any(p.get("state") == "ACTIVE" for p in ports):
        errors.append("%s: RDMA port %s is %s" % (where, ports[0]["dev"], ports[0].get("state")))
    if want.get("rdma_ip") and want["rdma_ip"] not in addrs:
        errors.append("%s: rdma_ip %s/%s is not on the NIC" % (where, want["rdma_ip"], want.get("prefix")))
    elif not addrs:
        hint = "; set rdma_ip in rack-profile.yaml or configure the NIC" if mode == "site" else ""
        errors.append("%s: has no IPv4 address, which RoCE v2 needs%s" % (where, hint))
    v2 = [(p, g) for p in ports if p.get("link_layer") == "Ethernet"
          for g in p.get("gids", []) if g.get("type") == "RoCE v2" and g.get("ipv4") in addrs]
    if addrs and ports and not v2 and not errors:
        errors.append("%s: has no RoCE v2 GID for %s" % (where, ", ".join(addrs)))
    port, gid = v2[0] if v2 else (ports[0] if ports else {}, {})
    if got.get("mtu") != want.get("mtu"):
        msg = "%s: MTU is %s, not %s" % (where, got.get("mtu"), want.get("mtu"))
        if mode == "site":
            warnings.append(msg + " (the site configures this NIC; network.rdma.mtu says %s)" % want.get("mtu"))
        else:
            errors.append(msg)

    prio, dscp = settings["priority"], settings["dscp"]
    pfc = got.get("pfc")
    if settings.get("pfc") and pfc is not None:
        if prio not in pfc:
            warnings.append("%s: PFC is off on priority %s, so RoCE is not lossless here" % (where, prio))
        if set(pfc) - {prio}:
            warnings.append("%s: PFC is also on priorities %s, where other traffic can be paused"
                            % (where, ",".join(str(p) for p in sorted(set(pfc) - {prio}))))
    dmap = got.get("dscp_prio")
    if dmap is not None and str(dscp) not in dmap:
        warnings.append("%s: DSCP %s is not mapped to priority %s" % (where, dscp, prio))
    elif dmap is not None and dmap[str(dscp)] != prio:
        warnings.append("%s: DSCP %s is mapped to priority %s, not %s" % (where, dscp, dmap[str(dscp)], prio))
    ecn = got.get("ecn")
    if settings.get("ecn") and ecn is not None and not (ecn.get("rp") and ecn.get("np")):
        warnings.append("%s: ECN congestion control is off on priority %s" % (where, prio))
    tos = {p.get("roce_tos") for p in ports if p.get("link_layer") == "Ethernet"}
    if tos - {None, 0, dscp * 4}:
        warnings.append("%s: the RDMA-CM default ToS is %s, not %s (DSCP %s)"
                        % (where, ",".join(str(t) for t in sorted(tos - {None, 0})), dscp * 4, dscp))
    elif tos and tos <= {None, 0}:
        warnings.append("%s: the RDMA-CM default ToS is not set, so RDMA-CM traffic is not marked DSCP %s"
                        % (where, dscp))

    if errors:
        warnings = []  # a NIC that does not work: its settings don't matter yet
    pcie = got.get("pcie") or {}
    link = max([p.get("rate_gbps") or 0 for p in ports] + [(got.get("speed_mbps") or 0) // 1000])
    pcie_gbps = _pcie_gbps(pcie)
    record = {
        "mode": mode,
        "driver": got.get("driver"),
        "dev": port.get("dev"),
        "gid_index": gid.get("index"),
        "ipv4": gid.get("ipv4") or (addrs[0] if addrs else None),
        "network": next((str(ipaddress.ip_interface(a).network) for a in got.get("addrs", [])
                         if gid.get("ipv4") and a.split("/")[0] == gid["ipv4"]), None),
        "mtu": got.get("mtu"),
        "link_gbps": link or None,
        "pcie": "%s GT/s x%s" % (pcie.get("speed_gts"), pcie.get("width")) if pcie_gbps else None,
        "ceiling_gbps": min(x for x in (link, pcie_gbps) if x) if (link or pcie_gbps) else None,
        "numa_node": got.get("numa_node"),
        "cpus": got.get("cpulist"),
        "pfc": pfc,
        "dscp_prio": dmap,
        "ecn": "unknown" if ecn is None else "on" if ecn.get("rp") and ecn.get("np") else "off",
        "roce_tos": max((t for t in tos if t is not None), default=None),
        "usable": not errors,
    }
    return errors, warnings, record


def rdma_readback_evaluate(readbacks, expected, settings):
    """{"errors": [...], "warnings": [...], "record": {host: {nic: {...}}}}."""
    errors, warnings, record, unpackaged = [], [], {}, {}
    for host in sorted(expected):
        got = readbacks.get(host) or {}
        core = got.get("rdma_core") or {}
        if core.get("version") and core.get("packaged") is False:
            unpackaged.setdefault(core["version"], []).append(host)
        for want in expected[host].get("nics") or []:
            e, w, r = _nic_problems(host, want["nic"], want, (got.get("nics") or {}).get(want["nic"]),
                                    expected[host].get("mgmt_ip"), settings)
            errors += e
            warnings += w
            if r is not None:
                record.setdefault(host, {})[want["nic"]] = dict(r, rdma_core=core.get("version"))
    # The site replaced the OS's rdma-core, as kernels whose RDMA driver needs a newer one require.
    for version, hosts in sorted(unpackaged.items()):
        warnings.append("%s: RDMA runs on rdma-core %s, which no OS package installed. RDMA app images for these "
                        "nodes need an rdma-core that works with their kernel, like this one: an image with the "
                        "OS's own rdma-core may fail with \"Couldn't create QP\"" % (", ".join(hosts), version))
    return {"errors": errors, "warnings": warnings, "record": record}


def rdma_netplan_conflicts(readbacks, nics_by_host):
    """Errors for the dedicated NICs with rdma_ip that something else configures.

    99-rdma.yaml gives such a NIC only its rdma_ip, so a NIC that carries an IPv4
    address outside network.rdma.subnet (which holds no mgmt_ip), or that a bond,
    bridge or VLAN is built on, would lose that: the management NIC, typically. The
    live state is read, as the management NIC always has its address. Addresses in
    the subnet are an earlier install's; link-local ones are nobody's. A NIC that
    does not exist is the read-back's to report.
    """
    errors = []
    for host in sorted(nics_by_host):
        got_nics = (readbacks.get(host) or {}).get("nics") or {}
        for want in nics_by_host[host] or []:
            got = got_nics.get(want["nic"]) or {}
            if "rdma_ip" not in want or not got.get("exists"):
                continue
            rdma_net = ipaddress.ip_interface("%s/%s" % (want["rdma_ip"], want["prefix"])).network
            others = [a for a in got.get("addrs") or []
                      if ipaddress.ip_interface(a).ip not in rdma_net and not ipaddress.ip_interface(a).is_link_local]
            what = (["carries %s" % ", ".join(others)] if others else []) + \
                   (["is part of %s" % ", ".join(got["uppers"])] if got.get("uppers") else [])
            if what:
                errors.append("%s %s %s, so something else configures it (the management NIC?, or an install "
                              "with another network.rdma.subnet), and rdma_ip would replace that. Give rdma_ip to "
                              "a NIC nothing else configures, or remove rdma_ip and configure the NIC yourself"
                              % (host, want["nic"], " and ".join(what)))
    return errors


def rdma_qos_plan(readbacks, expected, settings):
    """{"plan": {host: {nic: cfg}}, "kept": [...]}: the RoCE settings rack-rdma-qos takes on.

    A NIC's PFC and DSCP map are the installer's when its state file lists the NIC, or when
    dcb reads none on the host. Settings the site applied are kept, and so are those the
    NIC's firmware DCBX agent takes from the switch (ice's fw-lldp-agent). The RDMA-CM
    default ToS is the installer's while it is unset, and a dedicated NIC's ARP settings
    while they are the kernel's defaults.
    """
    plan, kept = {}, []
    for host in sorted(expected):
        rb = readbacks.get(host) or {}
        ours = rb.get("installer_qos") or {}
        for want in expected[host].get("nics") or []:
            nic = want["nic"]
            got = (rb.get("nics") or {}).get(nic) or {}
            ports = [p for p in got.get("rdma") or [] if p.get("link_layer") == "Ethernet"]
            if not got.get("exists") or not ports:
                continue
            mine = ours.get(nic) or {}
            firmware = got.get("fw_lldp_agent") == "on"
            readable = got.get("pfc") is not None and got.get("dscp_prio") is not None
            site = bool(got.get("pfc")) or bool(got.get("dscp_prio"))
            dcb = bool(mine.get("dscp_map")) or (readable and not site and not firmware)
            arp = got.get("arp") or {}
            cfg = {"dscp": settings["dscp"], "priority": settings["priority"],
                   "dev": ports[0]["dev"], "port": ports[0]["port"],
                   "pfc": dcb and bool(settings.get("pfc")), "dscp_map": dcb,
                   "tos": bool(mine.get("tos")) or ports[0].get("roce_tos") in (None, 0),
                   # a shared NIC is the fabric's
                   "arp": not want.get("shared") and (bool(mine.get("arp"))
                                                      or (arp.get("ignore"), arp.get("announce")) == (0, 0))}
            if cfg["pfc"] or cfg["dscp_map"] or cfg["tos"] or cfg["arp"]:
                plan.setdefault(host, {})[nic] = cfg
            if dcb:
                continue
            if firmware:
                why = "the NIC's firmware DCBX agent sets PFC and DSCP from the switch"
            elif site:
                why = "the site's PFC and DSCP settings are kept"
            else:
                why = "dcb cannot read the NIC's PFC and DSCP settings, so they are left"
            kept.append("%s %s: %s" % (host, nic, why))
    return {"plan": plan, "kept": kept}


def rdma_bw_pairs(record, hosts):
    """The ib_write_bw runs: a ring over the NICs of each subnet.

    Each NIC sends to the next NIC in the ring that is on another node, so every NIC is
    tested. Within a subnet the traffic leaves by the NIC being tested; across subnets the
    route could pick another of the node's NICs.
    """
    groups = {}
    for h, host in enumerate(hosts):
        for pos, (nic, rec) in enumerate((record.get(host) or {}).items()):
            if rec.get("usable"):
                groups.setdefault(rec.get("network"), []).append(((pos, h), host, nic, rec))
    pairs = []
    for key in sorted(groups, key=str):
        ring = [m[1:] for m in sorted(groups[key], key=lambda m: m[0])]
        if len({host for host, _, _ in ring}) < 2:
            continue
        for i, (client, cnic, crec) in enumerate(ring):
            server, snic, srec = next(m for m in ring[i + 1:] + ring[:i] if m[0] != client)
            ceilings = [c for c in (crec.get("ceiling_gbps"), srec.get("ceiling_gbps")) if c]
            pairs.append({
                "client": client, "client_nic": cnic, "client_dev": crec["dev"], "client_cpus": crec.get("cpus"),
                "server": server, "server_nic": snic, "server_dev": srec["dev"], "server_cpus": srec.get("cpus"),
                "server_ip": srec["ipv4"], "ceiling_gbps": min(ceilings) if ceilings else None,
                "client_rdma_core": crec.get("rdma_core"),
            })
    return pairs


def rdma_bw_gbps(output):
    """The BW average [Gb/sec] that ib_write_bw --report_gbits prints, or None."""
    lines = (output or "").splitlines()
    for i, line in enumerate(lines):
        if "BW average" in line:
            for row in lines[i + 1:]:
                cols = row.split()
                if len(cols) >= 4 and all(re.match(r"^[\d.]+$", c) for c in cols[:4]):
                    return float(cols[3])
    return None


def _prio_counter(name, priority):
    return (re.search(r"(pri|prio|priority)_?%d(?!\d)" % priority, name, re.I)
            and re.search(r"pfc|pause|xoff", name, re.I) and not NOT_PFC_FRAMES.search(name))


def rdma_counter_deltas(before, after, priority):
    """Per host and NIC: PFC frames on the RoCE priority, ECN-marked packets and retransmit causes."""
    out = {}
    for host, rb in (after or {}).items():
        for nic, now in (rb.get("nics") or {}).items():
            was = (((before or {}).get(host) or {}).get("nics") or {}).get(nic) or {}
            moved = {}
            for kind, src in (("eth", "counters"), ("rdma", "rdma_counters")):
                for name, value in (now.get(src) or {}).items():
                    delta = value - (was.get(src) or {}).get(name, value)
                    if delta > 0:
                        moved[name] = delta
            out.setdefault(host, {})[nic] = {
                "pfc_rx": sum(v for k, v in moved.items() if k.lower().startswith("rx") and _prio_counter(k, priority)),
                "pfc_tx": sum(v for k, v in moved.items() if k.lower().startswith("tx") and _prio_counter(k, priority)),
                "ecn": sum(v for k, v in moved.items() if ECN.search(k)),
                "loss": sum(v for k, v in moved.items() if LOSS.search(k)),
            }
    return out


def rdma_bw_report(runs, deltas, low):
    """{"errors", "warnings", "lines"} for the ib_write_bw runs and the counters that moved.

    A run that measured nothing is an error. One below `low` of its ceiling, and
    packets dropped and retransmitted, are warnings: the fabric works, but not as it could.
    """
    errors, warnings, lines = [], [], []
    if not runs:
        lines.append("no bandwidth runs: each RDMA network needs NICs on two of the nodes in this run; "
                     "validate fabric_rdma measures the whole rack")
    for r in runs or []:
        what = "%s %s -> %s %s (%s)" % (r["client"], r["client_nic"], r["server"], r["server_nic"], r["server_ip"])
        if r.get("gbps") is None:
            output = " ".join(r.get("output") or []) or "no output"
            if QP_FAILED.search(output):
                output = output.rstrip(".") + (
                    ". %s could not create an RDMA queue pair: its rdma-core%s probably does not work with its "
                    "kernel's RDMA driver; install a newer rdma-core on it"
                    % (r["client"], " (%s)" % r["client_rdma_core"] if r.get("client_rdma_core") else ""))
            errors.append("%s: ib_write_bw measured nothing: %s" % (what, output))
            continue
        ceiling = r.get("ceiling_gbps")
        lines.append("%s: %.1f Gb/s%s" % (what, r["gbps"], " of up to %s" % ceiling if ceiling else ""))
        if ceiling and r["gbps"] < low * ceiling:
            warnings.append("%s: %.1f Gb/s is under %d%% of the %s Gb/s that its link and PCIe allow"
                            % (what, r["gbps"], round(low * 100), ceiling))
    for host in sorted(deltas or {}):
        for nic, d in sorted(deltas[host].items()):
            lines.append("%s %s: PFC pauses received %d, sent %d; ECN-marked %d; retransmitted %d"
                         % (host, nic, d["pfc_rx"], d["pfc_tx"], d["ecn"], d["loss"]))
            if d["loss"]:
                warnings.append("%s %s: %d RoCE packets were dropped and retransmitted: the network is lossy for "
                                "RoCE (PFC or ECN off on the hosts or the switches)" % (host, nic, d["loss"]))
    return {"errors": errors, "warnings": warnings, "lines": lines}


class FilterModule:
    def filters(self):
        return {
            "rdma_readback_evaluate": rdma_readback_evaluate,
            "rdma_bw_pairs": rdma_bw_pairs,
            "rdma_bw_gbps": rdma_bw_gbps,
            "rdma_counter_deltas": rdma_counter_deltas,
            "rdma_bw_report": rdma_bw_report,
            "rdma_qos_plan": rdma_qos_plan,
            "rdma_netplan_conflicts": rdma_netplan_conflicts,
        }
