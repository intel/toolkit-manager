#!/usr/bin/env python3
# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
"""RDMA read-back: reads RDMA_READBACK_SPEC ({"nics": [...]}), prints what it finds as JSON, changes nothing.

Per NIC: link, addresses, PCIe link and NUMA node, its RDMA device and RoCE v2 GIDs, the
host's PFC, DSCP and ARP settings, ECN where the driver shows it, and the PFC, ECN and
retransmit counters. Standard library only, Python 3.6+.
"""

import ipaddress
import json
import os
import re
import shutil
import subprocess

COUNTER = re.compile(r"pfc|pause|xon|xoff", re.I)
RDMA_COUNTER = re.compile(r"ecn|seq", re.I)
QOS_STATE = "/etc/rack-rdma-qos.json"
CONFIGFS = "/sys/kernel/config/rdma_cm"


def run(args):
    path = shutil.which(args[0])
    if not path:
        return None, ""
    try:
        res = subprocess.run([path] + args[1:], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             universal_newlines=True, timeout=10, env=dict(os.environ, LC_ALL="C"))
        return res.returncode, res.stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return -1, str(exc)


def read(path, default=None):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return default


def number(text, kind=int):
    try:
        return kind(text)
    except (TypeError, ValueError):
        return None


def pcie(dev):
    def gts(name):
        m = re.match(r"([\d.]+)\s*GT/s", read(os.path.join(dev, name), "") or "")
        return float(m.group(1)) if m else None
    return {"speed_gts": gts("current_link_speed"), "width": number(read(os.path.join(dev, "current_link_width")))}


def v4_gid(gid):
    """The IPv4 address of an IPv4-mapped GID, or None."""
    if not gid.startswith("0000:0000:0000:0000:0000:ffff:"):
        return None
    tail = gid.split(":")[-2:]
    return str(ipaddress.IPv4Address(int(tail[0] + tail[1], 16)))


def rdma_ports(nic):
    """The RDMA ports whose GIDs or PCI function belong to the NIC."""
    ports = []
    base = "/sys/class/infiniband"
    for dev in sorted(os.listdir(base)) if os.path.isdir(base) else []:
        dpath = os.path.join(base, dev)
        same_fn = nic in (os.listdir(os.path.join(dpath, "device", "net"))
                          if os.path.isdir(os.path.join(dpath, "device", "net")) else [])
        for port in sorted(os.listdir(os.path.join(dpath, "ports"))):
            ppath = os.path.join(dpath, "ports", port)
            gids = []
            ndevs = os.path.join(ppath, "gid_attrs", "ndevs")
            for idx in sorted(os.listdir(ndevs), key=int) if os.path.isdir(ndevs) else []:
                if read(os.path.join(ndevs, idx)) != nic:
                    continue
                kind = read(os.path.join(ppath, "gid_attrs", "types", idx))
                gid = read(os.path.join(ppath, "gids", idx), "")
                gids.append({"index": int(idx), "type": kind, "ipv4": v4_gid(gid)})
            if not gids and not same_fn:
                continue
            rate = re.match(r"(\d+)", read(os.path.join(ppath, "rate"), "") or "")
            ports.append({
                "dev": dev, "port": int(port),
                "state": (read(os.path.join(ppath, "state"), "") or "").split(":")[-1].strip(),
                "link_layer": read(os.path.join(ppath, "link_layer")),
                "rate_gbps": int(rate.group(1)) if rate else None,
                # None: never set, so RDMA-CM marks nothing (ToS 0)
                "roce_tos": number(read(os.path.join(CONFIGFS, dev, "ports", port, "default_roce_tos"))),
                "gids": gids,
            })
    return ports


def pfc(nic):
    """Priorities with PFC on, or None when dcb can't tell."""
    rc, out = run(["dcb", "pfc", "show", "dev", nic])
    if rc != 0 or "prio-pfc" not in out:
        return None
    return [int(p) for p, state in re.findall(r"\b([0-7]):(on|off)\b", out.split("prio-pfc", 1)[1]) if state == "on"]


def dscp_prio(nic):
    """{dscp: priority} from the host's DSCP map, or None when dcb can't tell."""
    rc, out = run(["dcb", "-N", "app", "show", "dev", nic])
    if rc != 0:
        return None
    found = {}
    for part in out.split("dscp-prio", 1)[1:]:
        for dscp, prio in re.findall(r"\b(\d+):(\d)\b", part.split("\n")[0]):
            found[dscp] = int(prio)
    return found


def ecn(nic, priority):
    """mlx5 shows RoCE ECN per priority; other drivers do not (None)."""
    base = "/sys/class/net/%s/ecn" % nic
    if not os.path.isdir(base):
        return None
    return {side: read(os.path.join(base, "roce_%s" % side, "enable", str(priority))) == "1"
            for side in ("rp", "np")}


def counters(nic, ports):
    rc, out = run(["ethtool", "-S", nic])
    eth = {}
    if rc == 0:
        for line in out.splitlines():
            name, _, value = line.strip().partition(":")
            if COUNTER.search(name) and number(value.strip()) is not None:
                eth[name.strip()] = int(value)
    rdma = {}
    for p in ports:
        rc, out = run(["rdma", "statistic", "show", "link", "%s/%d" % (p["dev"], p["port"])])
        words = out.split() if rc == 0 else []
        for name, value in zip(words, words[1:]):
            if RDMA_COUNTER.search(name) and number(value) is not None:
                rdma["%s.%s" % (p["dev"], name)] = int(value)
    return eth, rdma


def fw_lldp_agent(nic):
    """ice: the firmware's LLDP agent owns DCB while it is on."""
    rc, out = run(["ethtool", "--show-priv-flags", nic])
    m = re.search(r"fw-lldp-agent\s*:\s*(on|off)", out) if rc == 0 else None
    return m.group(1) if m else None


def nic_record(nic, priority):
    net = "/sys/class/net/" + nic
    if not os.path.isdir(net):
        return {"exists": False}
    dev = os.path.join(net, "device")
    flags = number(read(os.path.join(net, "flags")), lambda v: int(v, 16)) or 0
    numa = number(read(os.path.join(dev, "numa_node")))
    _, addr = run(["ip", "-o", "-4", "addr", "show", "dev", nic])
    ports = rdma_ports(nic)
    eth, rdma = counters(nic, ports)
    return {
        "exists": True,
        "driver": os.path.basename(os.path.realpath(os.path.join(dev, "driver"))) if os.path.isdir(dev) else None,
        "admin_up": bool(flags & 1),
        "carrier": read(os.path.join(net, "carrier")) == "1" if flags & 1 else False,
        "mtu": number(read(os.path.join(net, "mtu"))),
        "speed_mbps": max(number(read(os.path.join(net, "speed"))) or 0, 0) or None,
        "addrs": re.findall(r"inet (\S+)", addr),
        "numa_node": numa if numa is not None and numa >= 0 else None,
        "cpulist": read("/sys/devices/system/node/node%d/cpulist" % numa) if numa is not None and numa >= 0 else None,
        "pcie": pcie(dev),
        "arp": {k: number(read("/proc/sys/net/ipv4/conf/%s/arp_%s" % (nic, k))) for k in ("ignore", "announce")},
        "rdma": ports,
        "pfc": pfc(nic),
        "dscp_prio": dscp_prio(nic),
        "fw_lldp_agent": fw_lldp_agent(nic),
        "ecn": ecn(nic, priority),
        "counters": eth,
        "rdma_counters": rdma,
    }


def main():
    spec = json.loads(os.environ.get("RDMA_READBACK_SPEC", "{}"))
    try:
        installer_qos = json.loads(read(QOS_STATE, "{}")).get("nics", {})
    except ValueError:
        installer_qos = {}
    print(json.dumps({
        "ib_write_bw": bool(shutil.which("ib_write_bw")),
        "installer_qos": installer_qos,
        "nics": {nic: nic_record(nic, spec.get("priority", 3)) for nic in spec.get("nics", [])},
    }, sort_keys=True))


if __name__ == "__main__":
    main()
