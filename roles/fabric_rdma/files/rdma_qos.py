#!/usr/bin/env python3
# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
"""rack-rdma-qos apply|undo: the RDMA NIC settings the installer took on (fabric_rdma).

/etc/rack-rdma-qos.json lists them per NIC: PFC on the RoCE priority, the DSCP to
priority map, the RDMA-CM default ToS (DSCP x 4), and ARP that answers only for the
NIC's own addresses (arp_ignore 1, arp_announce 2), so a node with two NICs on one
network does not draw RDMA to the wrong one. It lists only settings the host had at
their defaults: the site's are never changed. rack-rdma-qos.service applies them at
boot; teardown undoes them. Standard library only, Python 3.6+.
"""

import json
import os
import shutil
import subprocess
import sys

STATE = "/etc/rack-rdma-qos.json"
CONFIGFS = "/sys/kernel/config/rdma_cm"
SYSCTL = "/proc/sys/net/ipv4/conf/%s/arp_%s"
NET = "/sys/class/net"


def run(args):
    path = shutil.which(args[0])
    if not path:
        return 127, "%s not found" % args[0]
    try:
        res = subprocess.run([path] + args[1:], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             universal_newlines=True, timeout=10, env=dict(os.environ, LC_ALL="C"))
        return res.returncode, res.stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return -1, str(exc)


def rdma_dev(nic, cfg):
    """The NIC's RDMA device as named now: rdma-core renames it (irdma0 to rocep...) after install."""
    try:
        return sorted(os.listdir(os.path.join(NET, nic, "device", "infiniband")))[0]
    except (OSError, IndexError):
        return cfg["dev"]


def apply(nic, cfg):
    problems = []
    prio, dscp = cfg["priority"], cfg["dscp"]
    if cfg.get("pfc"):
        rc, out = run(["dcb", "pfc", "set", "dev", nic, "prio-pfc", "all:off", "%d:on" % prio])
        if rc:
            problems.append("%s: PFC on priority %d: %s" % (nic, prio, out))
    if cfg.get("dscp_map"):
        entry = "%d:%d" % (dscp, prio)
        rc, out = run(["dcb", "app", "replace", "dev", nic, "dscp-prio", entry])
        if rc:  # older iproute2 has no replace
            rc, out = run(["dcb", "app", "add", "dev", nic, "dscp-prio", entry])
        if rc:
            problems.append("%s: DSCP %d to priority %d: %s" % (nic, dscp, prio, out))
    if cfg.get("tos"):
        dev = rdma_dev(nic, cfg)
        try:
            os.makedirs(os.path.join(CONFIGFS, dev), exist_ok=True)
            with open(os.path.join(CONFIGFS, dev, "ports", str(cfg["port"]), "default_roce_tos"), "w") as f:
                f.write(str(dscp * 4))
        except OSError as exc:
            problems.append("%s: RDMA-CM default ToS on %s: %s" % (nic, dev, exc))
    if cfg.get("arp"):
        problems += set_arp(nic, ignore=1, announce=2)
        # Entries learnt from the wrong NIC before this would linger.
        run(["ip", "neigh", "flush", "dev", nic])
    return problems


def set_arp(nic, ignore, announce):
    problems = []
    for key, value in (("ignore", ignore), ("announce", announce)):
        try:
            with open(SYSCTL % (nic, key), "w") as f:
                f.write(str(value))
        except OSError as exc:
            problems.append("%s: arp_%s %d: %s" % (nic, key, value, exc))
    return problems


def undo(nic, cfg):
    # What is already gone is not a problem.
    if cfg.get("pfc"):
        run(["dcb", "pfc", "set", "dev", nic, "prio-pfc", "all:off"])
    if cfg.get("dscp_map"):
        run(["dcb", "app", "del", "dev", nic, "dscp-prio", "%d:%d" % (cfg["dscp"], cfg["priority"])])
    if cfg.get("tos"):
        try:
            os.rmdir(os.path.join(CONFIGFS, rdma_dev(nic, cfg)))
        except OSError:
            pass
    if cfg.get("arp"):
        set_arp(nic, ignore=0, announce=0)


def main(argv):
    if len(argv) != 2 or argv[1] not in ("apply", "undo"):
        print("usage: rack-rdma-qos apply|undo")
        return 2
    try:
        with open(STATE) as f:
            nics = json.load(f).get("nics", {})
    except (OSError, ValueError):
        nics = {}
    problems = []
    for nic, cfg in sorted(nics.items()):
        if argv[1] == "apply":
            problems += apply(nic, cfg)
        else:
            undo(nic, cfg)
    for p in problems:
        print("rack-rdma-qos: %s" % p)
    print("rack-rdma-qos: %s %d NIC(s)%s" % (argv[1], len(nics), ", %d problem(s)" % len(problems) if problems else ""))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
