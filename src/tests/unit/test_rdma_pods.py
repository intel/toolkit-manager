# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
# Run: python3 -m pytest src/tests/unit
"""RDMA for pods: the device plugin's config and the pod networks (DCAIDSE8-2583).

The nodes: one with a Broadcom Thor (ens785np0), two with two (ens6np0, and
ens28np0 with an rdma_ip), and a Clos node whose RDMA NIC is its fabric NIC (shared).
"""
from plugin_loader import load_plugin

_mod = load_plugin("rdma_pods")


def dedicated(nic, **extra):
    return {"nic": nic, "mtu": 9000, "shared": False, **extra}


NICS = {
    "icx1": [dedicated("ens785np0")],
    "gnr1": [dedicated("ens6np0"), dedicated("ens28np0", rdma_ip="192.168.40.11", prefix=24)],
    "gnr2": [dedicated("ens6np0"), dedicated("ens28np0", rdma_ip="192.168.40.13", prefix=24)],
    "clos1": [{"nic": "ens786f0np0", "mtu": 9100, "shared": True}],
}


def test_network_i_is_each_nodes_ith_dedicated_nic():
    assert _mod.rdma_networks(NICS) == [
        {"index": 0, "name": "rdma-net0",
         "nics": {"icx1": "ens785np0", "gnr1": "ens6np0", "gnr2": "ens6np0"}},
        {"index": 1, "name": "rdma-net1",
         "nics": {"gnr1": "ens28np0", "gnr2": "ens28np0"}},
    ]
    assert _mod.rdma_networks({"clos1": NICS["clos1"]}) == []


def test_plugin_config_selects_the_nics_by_name():
    config = _mod.rdma_device_plugin_config(NICS, 64, 300)
    assert config == {"periodicUpdateInterval": 300, "configList": [
        {"resourcePrefix": "rdma", "resourceName": "hca", "rdmaHcaMax": 64,
         "selectors": {"ifNames": ["ens28np0", "ens6np0", "ens785np0", "ens786f0np0"]}},
        {"resourcePrefix": "rdma", "resourceName": "net0", "rdmaHcaMax": 64,
         "selectors": {"ifNames": ["ens6np0", "ens785np0"]}},
        {"resourcePrefix": "rdma", "resourceName": "net1", "rdmaHcaMax": 64,
         "selectors": {"ifNames": ["ens28np0"]}},
    ]}


def test_plugin_config_never_has_an_empty_selector():
    # An empty ifNames list would select every RDMA device of the node.
    assert _mod.rdma_device_plugin_config({}, 64, 300)["configList"] == []
    assert _mod.rdma_device_plugin_config({"n1": []}, 64, 300)["configList"] == []
    only_shared = _mod.rdma_device_plugin_config({"clos1": NICS["clos1"]}, 64, 300)["configList"]
    assert [c["resourceName"] for c in only_shared] == ["hca"]


def test_resources_a_node_advertises():
    assert _mod.rdma_node_resources(NICS["gnr1"]) == ["rdma/hca", "rdma/net0", "rdma/net1"]
    assert _mod.rdma_node_resources(NICS["icx1"]) == ["rdma/hca", "rdma/net0"]
    assert _mod.rdma_node_resources(NICS["clos1"]) == ["rdma/hca"]
    assert _mod.rdma_node_resources([]) == []


def test_missing_resources_count_zero_as_missing():
    allocatable = {"cpu": "72", "rdma/hca": "64", "rdma/net0": "64", "rdma/net1": "0"}
    assert _mod.rdma_missing_resources(NICS["gnr1"], allocatable) == ["rdma/net1"]
    assert _mod.rdma_missing_resources(NICS["icx1"], allocatable) == []
    assert _mod.rdma_missing_resources(NICS["icx1"], {}) == ["rdma/hca", "rdma/net0"]
    assert _mod.rdma_missing_resources([], None) == []


def test_cni_config_per_node_names_its_own_nic():
    files = _mod.rdma_cni_files(NICS, "192.168.40.0/24", "192.168.40.128/26")
    assert [(f["host"], f["name"], f["conf"]["master"]) for f in files] == [
        ("gnr1", "rdma-net0", "ens6np0"), ("gnr1", "rdma-net1", "ens28np0"),
        ("gnr2", "rdma-net0", "ens6np0"), ("gnr2", "rdma-net1", "ens28np0"),
        ("icx1", "rdma-net0", "ens785np0"),
    ]
    assert files[1]["conf"] == {
        "cniVersion": "0.3.1", "name": "rdma-net1", "type": "ipvlan", "master": "ens28np0", "mode": "l2",
        "ipam": {"type": "whereabouts", "range": "192.168.40.0/24",
                 "range_start": "192.168.40.128", "range_end": "192.168.40.191"}}


def record(usable=True, dev="bnxt_re0", ceiling=252, cpus="0-35"):
    return {"usable": usable, "dev": dev, "ceiling_gbps": ceiling, "cpus": cpus}


def test_pod_pairs_one_run_per_network_on_its_first_two_working_nodes():
    networks = _mod.rdma_networks(NICS)
    rec = {
        "gnr1": {"ens6np0": record(usable=False), "ens28np0": record(dev="bnxt_re2", ceiling=252)},
        "gnr2": {"ens6np0": record(dev="bnxt_re1", ceiling=400), "ens28np0": record(dev="bnxt_re2", ceiling=252)},
        "icx1": {"ens785np0": record(dev="bnxt_re0", ceiling=252)},
    }
    assert _mod.rdma_pod_pairs(networks, rec) == [
        {"network": "rdma-net0",
         "client": "icx1", "client_nic": "ens785np0", "client_dev": "bnxt_re0", "client_cpus": "0-35",
         "server": "gnr2", "server_nic": "ens6np0", "server_dev": "bnxt_re1", "server_cpus": "0-35",
         "ceiling_gbps": 252},
        {"network": "rdma-net1",
         "client": "gnr2", "client_nic": "ens28np0", "client_dev": "bnxt_re2", "client_cpus": "0-35",
         "server": "gnr1", "server_nic": "ens28np0", "server_dev": "bnxt_re2", "server_cpus": "0-35",
         "ceiling_gbps": 252},
    ]
    del rec["gnr2"]
    assert _mod.rdma_pod_pairs(networks, rec) == []  # one working node per network: nothing to measure


def test_daemonset_gets_the_image_and_runs_on_the_labelled_nodes_only():
    vendored = {"kind": "DaemonSet", "metadata": {"name": "kube-multus-ds"}, "spec": {"template": {"spec": {
        "containers": [{"name": "kube-multus", "image": "upstream"}],
        "initContainers": [{"name": "install-multus-binary", "image": "upstream"}],
        "tolerations": [{"operator": "Exists", "effect": "NoSchedule"}]}}}}
    spec = _mod.rdma_daemonset(vendored, "mirror/multus@sha256:1", "rdma-nics")["spec"]["template"]["spec"]
    assert [c["image"] for c in spec["containers"] + spec["initContainers"]] == ["mirror/multus@sha256:1"] * 2
    assert spec["tolerations"] == [{"operator": "Exists"}]
    assert spec["affinity"]["nodeAffinity"]["requiredDuringSchedulingIgnoredDuringExecution"] == {
        "nodeSelectorTerms": [{"matchExpressions": [{"key": "rdma-nics", "operator": "Exists"}]}]}
    assert vendored["spec"]["template"]["spec"]["containers"][0]["image"] == "upstream"


def daemonset(generation=2, observed=2, desired=3, updated=3, ready=3):
    return [{"metadata": {"generation": generation}, "status": {
        "observedGeneration": observed, "desiredNumberScheduled": desired,
        "updatedNumberScheduled": updated, "numberReady": ready}}]


def test_daemonset_ready_once_every_pod_runs_the_current_template():
    assert _mod.rdma_daemonset_ready(daemonset(), 3) is True
    assert _mod.rdma_daemonset_ready(daemonset(observed=1), 3) is False  # status of the previous apply
    assert _mod.rdma_daemonset_ready(daemonset(updated=2), 3) is False
    assert _mod.rdma_daemonset_ready(daemonset(ready=2), 3) is False
    assert _mod.rdma_daemonset_ready(daemonset(desired=2, updated=2, ready=2), 3) is False  # a node not scheduled yet
    assert _mod.rdma_daemonset_ready([], 0) is False
    assert _mod.rdma_daemonset_ready([{"metadata": {"generation": 1}}], 1) is False  # no status yet
