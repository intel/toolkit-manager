# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
# Run: python3 -m pytest src/tests/unit
import pathlib

import pytest
import yaml
from ansible_render import render, trust_as_template

_FACTS = yaml.safe_load((pathlib.Path(__file__).resolve().parents[3]
                         / "roles" / "fabric_inventory" / "tasks" / "facts.yaml").read_text())
PROFILE = {"summary": {"pod_cidr": "10.233.64.0/18", "service_cidr": "10.233.0.0/18"}}
GLOBAL_CONFIG_CHECK = "Fail if global_config.yaml sets a different pod or Service range"
CLUSTER_CHECK = "Fail if rack-profile.yaml does not name the installed cluster's ranges"


def task(name, tasks=_FACTS):
    for t in tasks:
        found = t if t["name"].endswith(name) else task(name, t.get("block", []))
        if found:
            return found
    return None


def variables(t, extra):
    return dict(extra, _rack_parsed=PROFILE, **{k: trust_as_template(v) for k, v in t.get("vars", {}).items()})


def runs(name, **extra):
    """Whether task name runs: its when list in order, stopping at the first false one, as Ansible does."""
    t = task(name)
    when = t["when"] if isinstance(t["when"], list) else [t["when"]]
    return all(render("{{ %s }}" % c, variables(t, extra)) in (True, "True") for c in when)


def kubeadm_config(pod="10.233.64.0/18", svc="10.233.0.0/18"):
    """The ClusterConfiguration kubectl prints; a BYO cluster may have no podSubnet."""
    lines = ["apiVersion: kubeadm.k8s.io/v1beta4", "kind: ClusterConfiguration", "networking:",
             "  dnsDomain: cluster.local"]
    lines += [f"  podSubnet: {pod}"] if pod else []
    return {"rc": 0, "stdout": "\n".join(lines + [f"  serviceSubnet: {svc}"])}


@pytest.mark.parametrize("var, key", [("kubernetes_cluster_cidr", "pod_cidr"),
                                      ("kubernetes_service_cidr", "service_cidr")])
def test_a_global_config_range_must_match_the_profile_on_install_only(var, key):
    item = {"var": var, "key": key}
    assert not runs(GLOBAL_CONFIG_CHECK, item=item, **{var: PROFILE["summary"][key]})
    assert runs(GLOBAL_CONFIG_CHECK, item=item, **{var: "10.244.0.0/16"})
    assert not runs(GLOBAL_CONFIG_CHECK, item=item, component_action="teardown", **{var: "10.244.0.0/16"})


@pytest.mark.parametrize("live, stops", [
    ({"rc": 1, "stdout": "", "stderr": "connection refused"}, False),   # no cluster yet
    ({"skipped": True, "changed": False}, False),                       # teardown: the read is skipped
    (kubeadm_config(pod=None), False),                                  # no podSubnet
    (kubeadm_config(), False),                                          # the profile's ranges
    (kubeadm_config(pod="10.244.0.0/16"), True),
    (kubeadm_config(svc="10.96.0.0/12"), True),
])
def test_the_profile_must_name_the_installed_clusters_ranges(live, stops):
    assert runs(CLUSTER_CHECK, _rack_live=live) is stops


def test_the_installed_cluster_is_read_on_install_only():
    name = "Read the installed cluster's pod and Service ranges"
    assert runs(name) and not runs(name, component_action="teardown")


def test_the_stop_gives_the_clusters_ranges():
    t = task(CLUSTER_CHECK)
    msg = render(t["ansible.builtin.fail"]["msg"], variables(t, {"_rack_live": kubeadm_config(pod="10.244.0.0/16")}))
    assert "Set network.pod_cidr: 10.244.0.0/16 and network.service_cidr: 10.233.0.0/18" in " ".join(msg.split())
