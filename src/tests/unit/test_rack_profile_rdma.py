# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
# Run: python3 -m pytest src/tests/unit
"""rdma_nics and network.rdma in rack-profile.yaml (DCAIDSE8-2541)."""
import copy

import yaml

from plugin_loader import load_plugin

_mod = load_plugin("rack_profile_parser")


def none_rack(**rdma):
    profile = {
        "site": {"name": "test"},
        "network": {"topology": "none", "calico_mode": "vxlan"},
        "racks": {"rack-01": {"nodes": {
            "cp1": {"hostname": "cp1", "mgmt_ip": "192.0.2.10", "roles": ["kube_control_plane", "etcd"]},
            "w1": {"hostname": "w1", "mgmt_ip": "192.0.2.20", "roles": ["kube_node"],
                   "rdma_nics": ["ens6np0"]},
            "w2": {"hostname": "w2", "mgmt_ip": "192.0.2.21", "roles": ["kube_node"],
                   "rdma_nics": [{"nic": "ens6np0"}]},
        }}},
    }
    if rdma:
        profile["network"]["rdma"] = rdma
    return profile


def clos_rack():
    return {
        "site": {"name": "test"},
        "network": {
            "topology": "clos", "calico_mode": "bgp", "fabric_prefix": 24, "control_plane_on_fabric": True,
            "leafs": [{"name": "leaf-a", "asn": 65001, "peer_ip": "10.10.1.1", "fabric_subnet": "10.10.1.0/24"}],
        },
        "racks": {"rack-01": {"nodes": {
            "cp1": {"hostname": "cp1", "mgmt_ip": "192.0.2.10", "roles": ["kube_control_plane", "etcd"],
                    "fabric_nics": [{"nic": "eth1", "fabric_ip": "10.10.1.10"}]},
            "w1": {"hostname": "w1", "mgmt_ip": "192.0.2.20", "roles": ["kube_node"],
                   "fabric_nics": [{"nic": "eth1", "fabric_ip": "10.10.1.20"}],
                   "rdma_nics": ["eth1"]},
        }}},
    }


def node(profile, name):
    return profile["racks"]["rack-01"]["nodes"][name]


def parse(profile):
    return _mod.rack_profile_parse(copy.deepcopy(profile))


def errors(profile):
    return _mod.rack_profile_validate(copy.deepcopy(profile))["errors"]


def hosts(profile):
    out = parse(profile)
    assert out["errors"] == []
    return yaml.safe_load(out["hosts_yaml"])


def settings(profile):
    return parse(profile)["summary"]["rdma"]


def test_dedicated_nics_by_name_or_mapping_get_the_default_mtu():
    inv = hosts(none_rack())
    for name in ("w1", "w2"):
        assert inv["all"]["hosts"][name]["node_rdma_nics"] == [{"nic": "ens6np0", "mtu": 9000, "shared": False}]
    assert "node_rdma_nics" not in inv["all"]["hosts"]["cp1"]
    assert list(inv["all"]["children"]["rdma_nodes"]["hosts"]) == ["w1", "w2"]


def test_default_roce_settings():
    assert settings(none_rack()) == {"dscp": 26, "priority": 3, "pfc": True, "ecn": True}


def test_site_roce_settings_replace_the_defaults():
    profile = none_rack(mtu=4200, dscp=34, priority=4, pfc=False, ecn=False)
    assert settings(profile) == {"dscp": 34, "priority": 4, "pfc": False, "ecn": False}
    assert hosts(profile)["all"]["hosts"]["w1"]["node_rdma_nics"][0]["mtu"] == 4200


def test_rack_without_rdma_nics_has_no_rdma_nodes():
    profile = none_rack()
    for name in ("w1", "w2"):
        del node(profile, name)["rdma_nics"]
    out = parse(profile)
    assert out["errors"] == []
    assert "rdma_nodes" not in yaml.safe_load(out["hosts_yaml"])["all"]["children"]


def test_rdma_ip_takes_its_prefix_from_the_subnet():
    profile = none_rack(subnet="192.168.40.0/24")
    node(profile, "w1")["rdma_nics"] = [{"nic": "ens28np0", "rdma_ip": "192.168.40.11"}]
    assert hosts(profile)["all"]["hosts"]["w1"]["node_rdma_nics"] == [
        {"nic": "ens28np0", "mtu": 9000, "shared": False, "rdma_ip": "192.168.40.11", "prefix": 24}]


def test_rdma_ip_needs_the_subnet():
    profile = none_rack()
    node(profile, "w1")["rdma_nics"] = [{"nic": "ens28np0", "rdma_ip": "192.168.40.11"}]
    assert errors(profile) == [
        "node 'w1' RDMA NIC 'ens28np0' has rdma_ip 192.168.40.11, but network.rdma.subnet is not set"]


def test_rdma_ip_must_be_an_assignable_address_in_the_subnet():
    profile = none_rack(subnet="192.168.40.0/24")
    node(profile, "w1")["rdma_nics"] = [{"nic": "ens28np0", "rdma_ip": "192.168.41.11"}]
    node(profile, "w2")["rdma_nics"] = [{"nic": "ens28np0", "rdma_ip": "192.168.40.255"}]
    assert errors(profile) == [
        "node 'w1' RDMA NIC 'ens28np0' rdma_ip 192.168.41.11 is outside network.rdma.subnet 192.168.40.0/24",
        "node 'w2' RDMA NIC 'ens28np0' rdma_ip 192.168.40.255 is the network or broadcast address of "
        "192.168.40.0/24 — not assignable"]
    node(profile, "w2")["rdma_nics"] = [{"nic": "ens28np0", "rdma_ip": "192.168.40.0"}]
    assert errors(profile)[1].endswith("192.168.40.0 is the network or broadcast address of 192.168.40.0/24 — not assignable")
    node(profile, "w2")["rdma_nics"] = [{"nic": "ens28np0", "rdma_ip": "not-an-ip"}]
    assert errors(profile) == ["node 'w2' rdma_ip: 'not-an-ip' is not a valid IP address"]


def test_duplicate_rdma_ip_and_duplicate_nic():
    profile = none_rack(subnet="192.168.40.0/24")
    node(profile, "w1")["rdma_nics"] = [{"nic": "ens28np0", "rdma_ip": "192.168.40.11"}]
    node(profile, "w2")["rdma_nics"] = [{"nic": "ens28np0", "rdma_ip": "192.168.40.11"}]
    assert errors(profile) == ["duplicate rdma_ip 192.168.40.11 claimed by: w1:ens28np0, w2:ens28np0"]
    profile = none_rack()
    node(profile, "w1")["rdma_nics"] = ["ens6np0", {"nic": "ens6np0"}]
    assert errors(profile) == ["node 'w1' rdma_nics lists 'ens6np0' twice"]


def test_a_node_gets_at_most_one_dedicated_nic_with_rdma_ip():
    profile = none_rack(subnet="192.168.40.0/24")
    node(profile, "w1")["rdma_nics"] = [{"nic": "ens6np0", "rdma_ip": "192.168.40.11"},
                                        {"nic": "ens28np0", "rdma_ip": "192.168.40.12"}]
    assert errors(profile) == [
        "node 'w1' has rdma_ip on ens6np0, ens28np0: network.rdma has one subnet, so a node gets at most one "
        "dedicated RDMA NIC with rdma_ip (per-rail subnets are not supported yet)"]
    node(profile, "w1")["rdma_nics"][0] = {"nic": "ens6np0"}  # the site configures it
    assert errors(profile) == []


def test_subnet_must_stay_off_the_fabric_cluster_and_management_networks():
    profile = clos_rack()
    profile["network"]["rdma"] = {"subnet": "10.10.0.0/16"}
    profile["network"]["pod_cidr"] = "10.10.128.0/17"
    profile["network"]["service_cidr"] = "10.10.64.0/18"
    found = errors(profile)
    assert any(e.startswith("network.rdma.subnet 10.10.0.0/16 overlaps fabric prefix 10.10.1.0/24") for e in found)
    assert "network.rdma.subnet 10.10.0.0/16 overlaps network.pod_cidr 10.10.128.0/17" in found
    assert "network.rdma.subnet 10.10.0.0/16 overlaps network.service_cidr 10.10.64.0/18" in found
    profile = none_rack(subnet="192.0.2.0/24")
    assert errors(profile) == [
        "network.rdma.subnet 192.0.2.0/24 contains mgmt_ip 192.0.2.10 of node 'cp1' — RDMA does not run "
        "on the management network",
        "network.rdma.subnet 192.0.2.0/24 contains mgmt_ip 192.0.2.20 of node 'w1' — RDMA does not run "
        "on the management network",
        "network.rdma.subnet 192.0.2.0/24 contains mgmt_ip 192.0.2.21 of node 'w2' — RDMA does not run "
        "on the management network"]


def test_fabric_nic_is_shared_with_the_fabric_mtu():
    profile = clos_rack()
    profile["network"]["mtu"] = 9100
    profile["network"]["rdma"] = {"mtu": 4200}
    assert hosts(profile)["all"]["hosts"]["w1"]["node_rdma_nics"] == [{"nic": "eth1", "mtu": 9100, "shared": True}]


def test_shared_nic_takes_no_rdma_ip():
    profile = clos_rack()
    profile["network"]["rdma"] = {"subnet": "192.168.40.0/24"}
    node(profile, "w1")["rdma_nics"] = [{"nic": "eth1", "rdma_ip": "192.168.40.11"}]
    assert errors(profile) == [
        "node 'w1' RDMA NIC 'eth1' is also a fabric NIC, so RDMA uses its fabric_ip — remove rdma_ip"]


def test_network_rdma_values_are_checked():
    found = errors(none_rack(mtu=1000, dscp=64, priority=8, pfc="yes", ecn=1, vlan=100))
    assert found == [
        "unknown field 'vlan' in network.rdma — typo?",
        "network.rdma.mtu must be a whole number from 1280 to 65535, got 1000",
        "network.rdma.dscp must be a whole number from 0 to 63, got 64",
        "network.rdma.priority must be a whole number from 0 to 7, got 8",
        "network.rdma.pfc must be true or false, got 'yes'",
        "network.rdma.ecn must be true or false, got 1"]
    assert errors(none_rack(subnet="192.168.40.0/33")) == [
        "network.rdma.subnet: '192.168.40.0/33' is not a valid CIDR network"]
    assert errors(none_rack(subnet="fd00::/64")) == ["network.rdma.subnet must be IPv4, got fd00::/64"]
    assert errors(none_rack(subnet="192.168.40.0/31")) == [
        "network.rdma.subnet 192.168.40.0/31 leaves no addresses for the nodes: use /30 or larger"]
    profile = none_rack()
    profile["network"]["rdma"] = ["subnet"]
    assert errors(profile) == ["network.rdma must be a mapping, got list"]


def test_rdma_nics_shape_is_checked():
    profile = none_rack()
    node(profile, "w1")["rdma_nics"] = "ens6np0"
    node(profile, "w2")["rdma_nics"] = [{"name": "ens6np0"}, 7, {"nic": "ens28np0", "rdma_ip": 3232245771}]
    assert errors(profile) == [
        "node 'w1' rdma_nics must be a list, e.g. rdma_nics: [ens28np0], got str",
        "unknown field 'name' in node 'w2' rdma_nics[0] — typo?",
        "node 'w2' rdma_nics[0] is missing required field 'nic'",
        "node 'w2' rdma_nics[1] must be a NIC name or a mapping with 'nic'",
        "node 'w2' rdma_nics[2] rdma_ip must be an address such as 192.168.40.11, got 3232245771"]

