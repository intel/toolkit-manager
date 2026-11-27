# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
"""RDMA for pods: the device plugin's config and the pod networks (DCAIDSE8-2583).

    {{ nics_by_host | rdma_networks }}
    {{ nics_by_host | rdma_device_plugin_config(hca_max, interval) }}
    {{ node_rdma_nics | rdma_node_resources }}
    {{ node_rdma_nics | rdma_missing_resources(allocatable) }}
    {{ nics_by_host | rdma_cni_files(subnet, pod_range) }}
    {{ networks | rdma_pod_pairs(record) }}
    {{ vendored_daemonset | rdma_daemonset(image, label) }}
    {{ k8s_info_resources | rdma_daemonset_ready(min_desired) }}

nics_by_host: {host: node_rdma_nics} from the inventory ({nic, mtu, shared, ...}).
RDMA network i is each node's i-th dedicated RDMA NIC; a shared NIC (also a fabric
NIC) is on no pod network. The parser makes sure a NIC name is on one network only.
"""

import copy
import ipaddress


def _dedicated(nics):
    return [n["nic"] for n in nics or [] if not n.get("shared")]


def rdma_networks(nics_by_host):
    """[{"index", "name", "nics": {host: nic}}], one per dedicated RDMA network."""
    out = []
    for host in sorted(nics_by_host):
        for i, nic in enumerate(_dedicated(nics_by_host[host])):
            if i == len(out):
                out.append({"index": i, "name": "rdma-net%d" % i, "nics": {}})
            out[i]["nics"][host] = nic
    return out


def rdma_device_plugin_config(nics_by_host, hca_max, interval):
    """The plugin's config.json: rdma/hca selects every RDMA NIC, rdma/net<i> network i's NICs.

    The plugin selects NICs by name on every node it runs on. An empty name list would
    select every RDMA device, so a rack without RDMA NICs gets no resources at all.
    """
    names = sorted({n["nic"] for nics in nics_by_host.values() for n in nics or []})
    resources = [("hca", names)] if names else []
    resources += [("net%d" % net["index"], sorted(set(net["nics"].values()))) for net in rdma_networks(nics_by_host)]
    return {"periodicUpdateInterval": interval, "configList": [
        {"resourcePrefix": "rdma", "resourceName": name, "rdmaHcaMax": hca_max, "selectors": {"ifNames": nics}}
        for name, nics in resources]}


def rdma_node_resources(nics):
    """The resources a node with these RDMA NICs advertises."""
    return (["rdma/hca"] if nics else []) + ["rdma/net%d" % i for i in range(len(_dedicated(nics)))]


def rdma_missing_resources(nics, allocatable):
    """Those of rdma_node_resources(nics) that the node's allocatable lacks or has at 0."""
    return [r for r in rdma_node_resources(nics) if int((allocatable or {}).get(r) or 0) <= 0]


def rdma_cni_files(nics_by_host, subnet, pod_range):
    """Each node's CNI config per pod network: [{"host", "name", "conf"}].

    A NetworkAttachmentDefinition with an empty spec makes Multus read the config of
    that name from the node, so each node names its own NIC. ipvlan L2: the pod
    shares the NIC's MAC (bnxt_re builds RoCE GIDs with it) and takes its MTU.
    Pods get pod_range addresses with the subnet's prefix, so they reach the
    nodes' rdma_ip on the link; whereabouts keeps them unique across the rack.
    """
    pods = ipaddress.ip_network(pod_range)
    return [{"host": host, "name": "rdma-net%d" % i, "conf": {
        "cniVersion": "0.3.1", "name": "rdma-net%d" % i, "type": "ipvlan", "master": nic, "mode": "l2",
        "ipam": {"type": "whereabouts", "range": subnet,
                 "range_start": str(pods.network_address), "range_end": str(pods.broadcast_address)}}}
        for host in sorted(nics_by_host) for i, nic in enumerate(_dedicated(nics_by_host[host]))]


def rdma_pod_pairs(networks, record):
    """One ib_write_bw run per pod network, between its first two nodes whose NIC works.

    record: fabric_rdma's read-back record, {host: {nic: {"usable", "dev", "cpus", ...}}}.
    """
    pairs = []
    for net in networks:
        ends = [(host, nic, record[host][nic]) for host, nic in sorted(net["nics"].items())
                if ((record.get(host) or {}).get(nic) or {}).get("usable")]
        if len(ends) < 2:
            continue
        (server, snic, srec), (client, cnic, crec) = ends[:2]
        ceilings = [c for c in (crec.get("ceiling_gbps"), srec.get("ceiling_gbps")) if c]
        pairs.append({
            "network": net["name"],
            "client": client, "client_nic": cnic, "client_dev": crec["dev"], "client_cpus": crec.get("cpus"),
            "server": server, "server_nic": snic, "server_dev": srec["dev"], "server_cpus": srec.get("cpus"),
            "ceiling_gbps": min(ceilings) if ceilings else None,
        })
    return pairs


def rdma_daemonset(daemonset, image, label):
    """A vendored DaemonSet with the role's image, on the nodes labelled `label` whatever their taints."""
    out = copy.deepcopy(daemonset)
    spec = out["spec"]["template"]["spec"]
    for container in spec["containers"] + spec.get("initContainers", []):
        container["image"] = image
    spec["tolerations"] = [{"operator": "Exists"}]
    spec["affinity"] = {"nodeAffinity": {"requiredDuringSchedulingIgnoredDuringExecution": {
        "nodeSelectorTerms": [{"matchExpressions": [{"key": label, "operator": "Exists"}]}]}}}
    return out


def rdma_daemonset_ready(resources, min_desired):
    """True once the DaemonSet (a k8s_info result) runs ready and updated on at least min_desired nodes."""
    if not resources:
        return False
    status = resources[0].get("status") or {}
    desired = int(status.get("desiredNumberScheduled") or 0)
    # Right after an apply the status can still describe the previous generation.
    return (int(status.get("observedGeneration") or 0) >= int(resources[0]["metadata"].get("generation") or 0)
            and desired >= min_desired
            and int(status.get("updatedNumberScheduled") or 0) == desired
            and int(status.get("numberReady") or 0) == desired)


class FilterModule:
    def filters(self):
        return {
            "rdma_networks": rdma_networks,
            "rdma_device_plugin_config": rdma_device_plugin_config,
            "rdma_node_resources": rdma_node_resources,
            "rdma_missing_resources": rdma_missing_resources,
            "rdma_cni_files": rdma_cni_files,
            "rdma_pod_pairs": rdma_pod_pairs,
            "rdma_daemonset": rdma_daemonset,
            "rdma_daemonset_ready": rdma_daemonset_ready,
        }
