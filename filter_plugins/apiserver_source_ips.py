# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
"""Addresses the host-network apiserver can call a pod from.

    {{ nodes | apiserver_source_ips(host_links) }}   # nodes: k8s_info Node resources

Each node's InternalIPs, plus its Calico tunnel addresses: across nodes the call
leaves through the CNI tunnel. host_links (optional) is `ip -j addr show` from
each control-plane node, parsed: its global addresses are added, since a pod on
the apiserver's own node is called from the node's first global address, not
always the node IP. Only single IP addresses are returned, so an annotation
holding a CIDR or junk cannot widen an AuthorizationPolicy.
"""

import ipaddress

CALICO_TUNNEL_ANNOTATIONS = (
    "projectcalico.org/IPv4VXLANTunnelAddr",
    "projectcalico.org/IPv4IPIPTunnelAddr",
    "projectcalico.org/IPv4WireguardInterfaceAddr",
    "projectcalico.org/IPv6VXLANTunnelAddr",
    "projectcalico.org/IPv6WireguardInterfaceAddr",
)


def _single_ip(value):
    try:
        return str(ipaddress.ip_address(str(value).strip()))
    except ValueError:
        return None


def apiserver_source_ips(nodes, host_links=None):
    """InternalIPs, then tunnel addresses, then host addresses; first-seen order, no duplicates."""
    nodes = nodes or []
    found = [
        a.get("address")
        for n in nodes
        for a in (n.get("status") or {}).get("addresses") or []
        if a.get("type") == "InternalIP"
    ]
    found += [
        ann[k]
        for n in nodes
        for ann in [(n.get("metadata") or {}).get("annotations") or {}]
        for k in CALICO_TUNNEL_ANNOTATIONS
        if k in ann
    ]
    found += [
        i.get("local")
        for links in host_links or []
        for link in links
        for i in link.get("addr_info", [])
        if i.get("scope") == "global"
    ]
    out = []
    for ip in map(_single_ip, found):
        if ip and ip not in out:
            out.append(ip)
    return out


class FilterModule:
    def filters(self):
        return {"apiserver_source_ips": apiserver_source_ips}
