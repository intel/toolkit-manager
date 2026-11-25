# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
# Run: python3 -m pytest src/tests/unit
"""The RDMA read-back and what it means (DCAIDSE8-2541).

The read-backs have the shape of real ones: Broadcom Thor (bnxt_re), Intel E810
(irdma) and NVIDIA ConnectX (mlx5) NICs.
"""
import copy
import importlib.util

import pytest

from plugin_loader import ROOT, load_plugin

_mod = load_plugin("rdma_readback")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


probe = _load("rdma_readback_probe", "roles/fabric_rdma/files/rdma_readback.py")
qos = _load("rdma_qos", "roles/fabric_rdma/files/rdma_qos.py")

SETTINGS = {"dscp": 26, "priority": 3, "pfc": True, "ecn": True}


def nic(dev="rocep75s0", driver="bnxt_en", ip="198.51.100.44", gen=16.0, width=16, rate=400, **over):
    record = {
        "exists": True, "driver": driver, "admin_up": True, "carrier": True, "mtu": 9000, "speed_mbps": rate * 1000,
        "addrs": ["%s/24" % ip] if ip else [], "numa_node": 0, "cpulist": "0-35,72-107",
        "pcie": {"speed_gts": gen, "width": width, "max_speed_gts": 32.0, "max_width": 16},
        "arp": {"ignore": 1, "announce": 2},
        "rdma": [{"dev": dev, "port": 1, "fw": "238.1.168.0", "state": "ACTIVE", "phys_state": "LinkUp",
                  "link_layer": "Ethernet", "rate_gbps": rate, "roce_tos": 104,
                  "gids": [{"index": 1, "type": "RoCE v2", "ipv4": None},
                           {"index": 3, "type": "RoCE v2", "ipv4": ip}]}],
        "pfc": [3], "dscp_prio": {"26": 3}, "dcbx": "host ieee", "fw_lldp_agent": None, "ecn": None,
        "counters": {"rx_pfc_ena_frames_pri3": 0, "tx_pfc_ena_frames_pri3": 0},
        "rdma_counters": {dev + ".np_ecn_marked_roce_packets": 0, dev + ".out_of_sequence": 0},
    }
    record.update(over)
    return record


def want(name="ens785np0", **over):
    return {"nic": name, "mtu": 9000, "shared": False, **over}


def evaluate(got, wanted=None, mgmt="192.0.2.19", settings=SETTINGS):
    wanted = wanted or want()
    return _mod.rdma_readback_evaluate({"n1": {"nics": {wanted["nic"]: got}}},
                                       {"n1": {"mgmt_ip": mgmt, "nics": [wanted]}}, settings)


def test_working_nic_is_recorded_with_its_pcie_ceiling():
    out = evaluate(nic())
    assert out["errors"] == [] and out["warnings"] == []
    rec = out["record"]["n1"]["ens785np0"]
    assert (rec["mode"], rec["dev"], rec["gid_index"], rec["ipv4"], rec["link_gbps"], rec["pcie"],
            rec["ceiling_gbps"], rec["ecn"], rec["usable"]) == (
        "site", "rocep75s0", 3, "198.51.100.44", 400, "16.0 GT/s x16", 252, "unknown", True)
    assert evaluate(nic(gen=32.0))["record"]["n1"]["ens785np0"]["ceiling_gbps"] == 400


def test_site_settings_that_differ_are_warnings():
    out = evaluate(nic(pfc=[], dscp_prio={}, mtu=1500))
    assert out["errors"] == []
    assert out["warnings"] == [
        "n1 ens785np0: MTU is 1500, not 9000 (the site configures this NIC; network.rdma.mtu says 9000)",
        "n1 ens785np0: PFC is off on priority 3, so RoCE is not lossless here",
        "n1 ens785np0: DSCP 26 is not mapped to priority 3"]
    assert evaluate(nic(pfc=[0, 1, 2, 3], dscp_prio={"26": 4}))["warnings"] == [
        "n1 ens785np0: PFC is also on priorities 0,1,2, where other traffic can be paused",
        "n1 ens785np0: DSCP 26 is mapped to priority 4, not 3"]


def test_unreadable_settings_and_settings_turned_off_give_no_warnings():
    assert evaluate(nic(pfc=None, dscp_prio=None))["warnings"] == []
    assert evaluate(nic(pfc=[]), settings={**SETTINGS, "pfc": False})["warnings"] == []


def test_ecn_off_on_mlx5():
    out = evaluate(nic(dev="mlx5_9", driver="mlx5_core", ecn={"rp": False, "np": True}), want("enp185s0f0np0"))
    assert out["warnings"] == ["n1 enp185s0f0np0: ECN congestion control is off on priority 3"]
    assert out["record"]["n1"]["enp185s0f0np0"]["ecn"] == "off"


def test_mtu_the_installer_sets_must_match():
    out = evaluate(nic(mtu=1500), want(rdma_ip="198.51.100.44", prefix=24))
    assert out["errors"] == ["n1 ens785np0: MTU is 1500, not 9000"]
    assert out["record"]["n1"]["ens785np0"]["mode"] == "dedicated"


def test_rdma_ip_must_be_on_the_nic():
    out = evaluate(nic(), want(rdma_ip="198.51.100.45", prefix=24))
    assert out["errors"] == ["n1 ens785np0: rdma_ip 198.51.100.45/24 is not on the NIC"]


def test_nic_without_ipv4():
    assert evaluate(nic(ip=None))["errors"] == [
        "n1 ens785np0: has no IPv4 address, which RoCE v2 needs; set rdma_ip in rack-profile.yaml or configure the NIC"]
    assert evaluate(nic(ip=None), want(shared=True))["errors"] == [
        "n1 ens785np0: has no IPv4 address, which RoCE v2 needs"]


def test_nic_without_a_v2_gid_for_its_address():
    got = nic()
    got["rdma"][0]["gids"] = [{"index": 0, "type": "IB/RoCE v1", "ipv4": "198.51.100.44"}]
    assert evaluate(got)["errors"] == ["n1 ens785np0: has no RoCE v2 GID for 198.51.100.44"]


def test_failing_nic_reports_errors_only():
    got = nic(dev="mlx5_1", driver="mlx5_core", ip=None, mtu=4092, admin_up=False, carrier=False, pfc=None)
    got["rdma"][0].update(link_layer="InfiniBand", gids=[])
    out = evaluate(got, want("ibs301f0"))
    assert out["errors"] == [
        "n1 ibs301f0: is an InfiniBand port; rack-scale RDMA is RoCE v2 on Ethernet",
        "n1 ibs301f0: is down",
        "n1 ibs301f0: has no IPv4 address, which RoCE v2 needs; set rdma_ip in rack-profile.yaml or configure the NIC"]
    assert out["warnings"] == [] and out["record"]["n1"]["ibs301f0"]["usable"] is False


def test_nic_without_an_rdma_device():
    assert evaluate(nic(driver="igb", rdma=[]))["errors"] == [
        "n1 ens785np0: has no RDMA device (driver igb: is its RDMA driver loaded?)"]


def test_link_and_port_state():
    assert evaluate(nic(carrier=False))["errors"] == ["n1 ens785np0: has no link"]
    got = nic()
    got["rdma"][0]["state"] = "DOWN"
    assert evaluate(got)["errors"] == ["n1 ens785np0: RDMA port rocep75s0 is DOWN"]


def test_management_nic_is_refused():
    assert evaluate(nic(ip="192.0.2.19"))["errors"] == [
        "n1 ens785np0: carries the management address 192.0.2.19; RDMA does not run on the management NIC"]


def test_missing_nic():
    assert evaluate({"exists": False})["errors"] == ["n1 ens785np0: no such NIC"]
    assert _mod.rdma_readback_evaluate({}, {"n1": {"nics": [want()]}}, SETTINGS)["errors"] == [
        "n1 ens785np0: no such NIC"]


def record(*hosts, mode="site", usable=True, network="198.51.100.0/24", nic="ens6np0"):
    return {h: {nic: {"mode": mode, "dev": "rocep42s0", "ipv4": "198.51.100.%d" % i, "network": network,
                      "cpus": "0-31", "ceiling_gbps": 400 - i, "usable": usable}}
            for i, h in enumerate(hosts, start=1)}


def pairs_of(rec):
    return _mod.rdma_bw_pairs(rec, list(rec))


def test_bw_pairs_form_a_ring_per_network():
    pairs = pairs_of(record("a", "b", "c"))
    assert [(p["client"], p["server"], p["server_ip"], p["ceiling_gbps"]) for p in pairs] == [
        ("a", "b", "198.51.100.2", 398), ("b", "c", "198.51.100.3", 397), ("c", "a", "198.51.100.1", 397)]


def test_bw_pairs_keep_networks_apart_and_skip_unusable_nics():
    rec = record("a", "b")
    rec.update(record("c", "d", mode="shared", network="10.201.0.0/24"))
    rec["e"] = record("e", usable=False)["e"]
    assert sorted((p["client"], p["server"]) for p in pairs_of(rec)) == [
        ("a", "b"), ("b", "a"), ("c", "d"), ("d", "c")]
    assert pairs_of(record("a")) == []


def test_bw_pairs_never_mix_a_gpu_rail_with_another_network():
    rec = record("gpu1", "gpu2", network="198.51.100.0/24")  # rail 0
    for h in rec:
        rec[h]["ens28np0"] = dict(rec[h]["ens6np0"], network="203.0.113.0/24")  # rail 1
    rec.update(record("store1", nic="ens785np0", network="192.0.2.0/24"))  # alone on its network
    assert sorted((p["client"], p["client_nic"], p["server"], p["server_nic"]) for p in pairs_of(rec)) == [
        ("gpu1", "ens28np0", "gpu2", "ens28np0"), ("gpu1", "ens6np0", "gpu2", "ens6np0"),
        ("gpu2", "ens28np0", "gpu1", "ens28np0"), ("gpu2", "ens6np0", "gpu1", "ens6np0")]


@pytest.mark.parametrize("second_nic_on", [("a", "b"), ("a",)])
def test_bw_pairs_send_from_every_nic_never_to_its_own_node(second_nic_on):
    rec = record("a", "b")
    for h in second_nic_on:
        rec[h]["ens28np0"] = dict(rec[h]["ens6np0"])
    pairs = pairs_of(rec)
    assert all(p["client"] != p["server"] for p in pairs)
    assert sorted((p["client"], p["client_nic"]) for p in pairs) == sorted(
        (h, n) for h in rec for n in rec[h])


def test_bw_report():
    run = {"client": "a", "client_nic": "x", "server": "b", "server_nic": "x", "server_ip": "198.51.100.2",
           "ceiling_gbps": 400}
    out = _mod.rdma_bw_report([dict(run, gbps=392.1), dict(run, gbps=150.0), dict(run, gbps=None, output=["timed out"])],
                              {"a": {"x": {"pfc_rx": 0, "pfc_tx": 0, "ecn": 0, "loss": 12}}}, 0.5)
    assert out["errors"] == ["a x -> b x (198.51.100.2): ib_write_bw measured nothing: timed out"]
    assert out["warnings"] == [
        "a x -> b x (198.51.100.2): 150.0 Gb/s is under 50% of the 400 Gb/s that its link and PCIe allow",
        "a x: 12 RoCE packets were dropped and retransmitted: the network is lossy for RoCE (PFC or ECN off on "
        "the hosts or the switches)"]
    assert out["lines"][0] == "a x -> b x (198.51.100.2): 392.1 Gb/s of up to 400"


def test_record_has_the_nics_network():
    assert evaluate(nic())["record"]["n1"]["ens785np0"]["network"] == "198.51.100.0/24"


def test_unknown_link_speed_leaves_the_pcie_ceiling():
    got = nic(speed_mbps=None, rdma=[])
    assert evaluate(got)["record"]["n1"]["ens785np0"]["ceiling_gbps"] == 252


IB_WRITE_BW = """\
---------------------------------------------------------------------------------------
                    RDMA_Write BW Test
 Dual-port       : OFF\t\tDevice         : rocep75s0
---------------------------------------------------------------------------------------
 #bytes     #iterations    BW peak[Gb/sec]    BW average[Gb/sec]   MsgRate[Mpps]
 65536      1781700          0.00               233.52 \t\t   0.445399
---------------------------------------------------------------------------------------
"""


def test_bw_gbps_reads_the_average():
    assert _mod.rdma_bw_gbps(IB_WRITE_BW) == 233.52
    assert _mod.rdma_bw_gbps("Couldn't connect to 198.51.100.2:18515") is None


@pytest.mark.parametrize("rx, tx, siblings", [
    ("rx_pfc_ena_frames_pri3", "tx_pfc_ena_frames_pri3", ["pfc_pri3_rx_duration_us", "rx_pfc_xon2xoff_frames_pri3"]),
    ("rx_prio3_pause", "tx_prio3_pause", ["rx_prio3_pause_duration", "rx_prio3_pause_transition"]),
    ("rx_priority_3_xoff.nic", "tx_priority_3_xoff.nic", ["rx_priority_3_xon.nic"]),
])
def test_counter_deltas_count_pfc_frames_on_the_roce_priority_only(rx, tx, siblings):
    names = [rx, tx, rx.replace("3", "0")] + siblings
    before = {"n1": {"nics": {"x": {"counters": dict.fromkeys(names, 0), "rdma_counters": {}}}}}
    after = copy.deepcopy(before)
    after["n1"]["nics"]["x"]["counters"] = dict.fromkeys(names, 50)
    after["n1"]["nics"]["x"]["counters"].update({rx: 4, tx: 3})
    assert _mod.rdma_counter_deltas(before, after, 3) == {"n1": {"x": {"pfc_rx": 4, "pfc_tx": 3, "ecn": 0, "loss": 0}}}


def test_counter_deltas_count_ecn_marks_and_retransmit_causes():
    names = ["d.np_ecn_marked_roce_packets", "d.np_cnp_sent", "d.out_of_sequence", "d.packet_seq_err"]
    before = {"n1": {"nics": {"x": {"counters": {}, "rdma_counters": dict.fromkeys(names, 0)}}}}
    after = copy.deepcopy(before)
    after["n1"]["nics"]["x"]["rdma_counters"] = dict(zip(names, (10, 5, 7, 2)))
    assert _mod.rdma_counter_deltas(before, after, 3)["n1"]["x"] == {"pfc_rx": 0, "pfc_tx": 0, "ecn": 10, "loss": 9}


def test_bw_report_with_no_runs_says_why():
    assert _mod.rdma_bw_report([], {}, 0.5)["lines"] == [
        "no bandwidth runs: each RDMA network needs NICs on two of the nodes in this run; "
        "validate fabric_rdma measures the whole rack"]


def test_probe_reads_ipv4_gids():
    assert probe.v4_gid("0000:0000:0000:0000:0000:ffff:c633:642c") == "198.51.100.44"
    assert probe.v4_gid("fe80:0000:0000:0000:8e84:74ff:fe5a:4290") is None


def test_probe_parses_dcb(monkeypatch):
    out = {("dcb", "pfc"): "pfc-cap 3 macsec-bypass off delay 0 prio-pfc 0:off 1:off 2:off 3:on 4:off 5:off 6:off 7:off",
           ("dcb", "-N"): "dscp-prio 26:3 48:6"}
    monkeypatch.setattr(probe, "run", lambda args: (0, out[tuple(args[:2])]))
    assert probe.pfc("ens785np0") == [3]
    assert probe.dscp_prio("ens785np0") == {"26": 3, "48": 6}
    monkeypatch.setattr(probe, "run", lambda args: (0, ""))
    assert probe.pfc("ens785np0") is None and probe.dscp_prio("ens785np0") == {}


def test_roce_tos_unset_or_different_warns():
    got = nic()
    got["rdma"][0]["roce_tos"] = None
    assert evaluate(got)["warnings"] == [
        "n1 ens785np0: the RDMA-CM default ToS is not set, so RDMA-CM traffic is not marked DSCP 26"]
    got["rdma"][0]["roce_tos"] = 96
    assert evaluate(got)["warnings"] == ["n1 ens785np0: the RDMA-CM default ToS is 96, not 104 (DSCP 26)"]


def plan(got, ours=None, settings=SETTINGS):
    return _mod.rdma_qos_plan({"n1": {"nics": {"ens785np0": got}, "installer_qos": ours or {}}},
                              {"n1": {"nics": [want()]}}, settings)


def test_plan_takes_on_a_nic_with_no_settings():
    got = nic(pfc=[], dscp_prio={})
    got["rdma"][0]["roce_tos"] = None
    assert plan(got) == {"plan": {"n1": {"ens785np0": {
        "dscp": 26, "priority": 3, "dev": "rocep75s0", "port": 1, "pfc": True, "dscp_map": True, "tos": True, "arp": False}}},
        "kept": []}
    assert plan(got, settings={**SETTINGS, "pfc": False})["plan"]["n1"]["ens785np0"]["pfc"] is False


def test_plan_keeps_the_sites_settings():
    got = nic(pfc=[], dscp_prio={"26": 3})  # the site maps DSCP 26 but leaves PFC off
    got["rdma"][0]["roce_tos"] = None
    assert plan(got) == {"plan": {"n1": {"ens785np0": {
        "dscp": 26, "priority": 3, "dev": "rocep75s0", "port": 1, "pfc": False, "dscp_map": False, "tos": True, "arp": False}}},
        "kept": ["n1 ens785np0: the site's PFC and DSCP settings are kept"]}
    assert plan(nic()) == {"plan": {}, "kept": ["n1 ens785np0: the site's PFC and DSCP settings are kept"]}


def test_plan_leaves_firmware_dcbx_and_unreadable_nics():
    assert plan(nic(pfc=[], dscp_prio={}, fw_lldp_agent="on"))["kept"] == [
        "n1 ens785np0: the NIC's firmware DCBX agent sets PFC and DSCP from the switch"]
    assert plan(nic(pfc=None, dscp_prio=None))["kept"] == [
        "n1 ens785np0: dcb cannot read the NIC's PFC and DSCP settings, so they are left"]


def test_plan_keeps_its_own_settings_on_a_reinstall():
    ours = {"ens785np0": {"dscp": 26, "priority": 3, "dev": "rocep75s0", "port": 1,
                          "pfc": True, "dscp_map": True, "tos": True, "arp": True}}
    assert plan(nic(), ours) == {"plan": {"n1": ours}, "kept": []}


def test_plan_skips_nics_without_an_ethernet_rdma_port():
    got = nic()
    got["rdma"][0]["link_layer"] = "InfiniBand"
    assert plan(got) == {"plan": {}, "kept": []}
    assert plan({"exists": False}) == {"plan": {}, "kept": []}


def test_qos_apply_and_undo(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(qos, "run", lambda args: calls.append(args) or (0, ""))
    monkeypatch.setattr(qos, "CONFIGFS", str(tmp_path))
    (tmp_path / "rocep75s0" / "ports" / "1").mkdir(parents=True)
    cfg = {"dscp": 26, "priority": 3, "dev": "rocep75s0", "port": 1, "pfc": True, "dscp_map": True, "tos": True}
    assert qos.apply("ens785np0", cfg) == []
    assert calls == [["dcb", "pfc", "set", "dev", "ens785np0", "prio-pfc", "all:off", "3:on"],
                     ["dcb", "app", "replace", "dev", "ens785np0", "dscp-prio", "26:3"]]
    assert (tmp_path / "rocep75s0" / "ports" / "1" / "default_roce_tos").read_text() == "104"
    calls.clear()
    qos.undo("ens785np0", cfg)
    assert calls == [["dcb", "pfc", "set", "dev", "ens785np0", "prio-pfc", "all:off"],
                     ["dcb", "app", "del", "dev", "ens785np0", "dscp-prio", "26:3"]]


def test_qos_falls_back_to_dcb_app_add_and_reports_failures(monkeypatch, tmp_path):
    answers = {"replace": (1, "Error: unknown command"), "add": (0, ""), "set": (1, "Operation not supported")}
    calls = []
    monkeypatch.setattr(qos, "run", lambda args: calls.append(args[2]) or answers[args[2]])
    cfg = {"dscp": 26, "priority": 3, "dev": "irdma0", "port": 1, "pfc": True, "dscp_map": True, "tos": False}
    assert qos.apply("ens6f0", cfg) == ["ens6f0: PFC on priority 3: Operation not supported"]
    assert calls == ["set", "replace", "add"]


def test_plan_takes_on_arp_at_the_kernel_defaults_on_dedicated_nics_only():
    got = nic(arp={"ignore": 0, "announce": 0})
    assert plan(got)["plan"]["n1"]["ens785np0"]["arp"] is True
    shared = _mod.rdma_qos_plan({"n1": {"nics": {"ens785np0": got}}},
                                {"n1": {"nics": [want(shared=True)]}}, SETTINGS)
    assert shared == {"plan": {}, "kept": ["n1 ens785np0: the site's PFC and DSCP settings are kept"]}
    assert plan(nic(arp={"ignore": 2, "announce": 0}))["plan"] == {}  # the site's


def test_qos_arp_apply_and_undo(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(qos, "run", lambda args: calls.append(args) or (0, ""))
    monkeypatch.setattr(qos, "SYSCTL", str(tmp_path / "%s.arp_%s"))
    cfg = {"dscp": 26, "priority": 3, "dev": "rocep184s0", "port": 1, "pfc": False, "dscp_map": False,
           "tos": False, "arp": True}
    assert qos.apply("ens28np0", cfg) == []
    assert ((tmp_path / "ens28np0.arp_ignore").read_text(), (tmp_path / "ens28np0.arp_announce").read_text()) == (
        "1", "2")
    assert calls == [["ip", "neigh", "flush", "dev", "ens28np0"]]
    qos.undo("ens28np0", cfg)
    assert ((tmp_path / "ens28np0.arp_ignore").read_text(), (tmp_path / "ens28np0.arp_announce").read_text()) == (
        "0", "0")


def test_bw_pairs_never_cross_subnets_on_dual_homed_shared_nics():
    rec = record("a", "b", mode="shared", network="10.201.0.0/16")
    for h in rec:
        rec[h]["ens28f0"] = dict(rec[h]["ens6np0"], network="10.202.0.0/16")
    assert sorted((p["client_nic"], p["server_nic"]) for p in pairs_of(rec)) == [
        ("ens28f0", "ens28f0"), ("ens28f0", "ens28f0"), ("ens6np0", "ens6np0"), ("ens6np0", "ens6np0")]


def test_qos_follows_a_renamed_rdma_device(monkeypatch, tmp_path):
    monkeypatch.setattr(qos, "NET", str(tmp_path / "net"))
    monkeypatch.setattr(qos, "CONFIGFS", str(tmp_path / "rdma_cm"))
    (tmp_path / "net" / "ens6f0" / "device" / "infiniband" / "rocep42s0f0").mkdir(parents=True)
    (tmp_path / "rdma_cm" / "rocep42s0f0" / "ports" / "1").mkdir(parents=True)
    cfg = {"dscp": 26, "priority": 3, "dev": "irdma0", "port": 1, "pfc": False, "dscp_map": False, "tos": True}
    assert qos.apply("ens6f0", cfg) == []
    assert (tmp_path / "rdma_cm" / "rocep42s0f0" / "ports" / "1" / "default_roce_tos").read_text() == "104"


@pytest.mark.parametrize("lib, owned, found", [
    ("libibverbs.so.1.14.50.0", True, {"version": 50, "packaged": True}),
    ("libibverbs.so.1.18.65.0", False, {"version": 65, "packaged": False}),
])
def test_probe_reads_the_rdma_core_release(monkeypatch, tmp_path, lib, owned, found):
    (tmp_path / lib).write_text("")
    (tmp_path / "libibverbs.so.1").symlink_to(lib)
    out = {"ldconfig": (0, "\tlibibverbs.so.1 (libc6,x86-64) => %s/libibverbs.so.1" % tmp_path),
           "dpkg": (0 if owned else 1, "")}
    monkeypatch.setattr(probe, "run", lambda args: out[args[0]])
    assert probe.rdma_core() == dict(found, lib=str(tmp_path / lib))
    monkeypatch.setattr(probe, "run", lambda args: (None, ""))
    assert probe.rdma_core() is None


def test_rdma_core_no_os_package_installed_warns_once_per_release():
    core = {"a": {"version": 65, "packaged": False}, "b": {"version": 65, "packaged": False},
            "c": {"version": 50, "packaged": True}}
    out = _mod.rdma_readback_evaluate(
        {h: {"nics": {"ens6np0": nic(ip="198.51.100.%d" % i)}, "rdma_core": core[h]} for i, h in enumerate(core, 1)},
        {h: {"nics": [want("ens6np0")]} for h in core}, SETTINGS)
    assert out["warnings"] == [
        "a, b: RDMA runs on rdma-core 65, which no OS package installed. RDMA app images for these nodes need an "
        "rdma-core that works with their kernel, like this one: an image with the OS's own rdma-core may fail "
        "with \"Couldn't create QP\""]
    assert [out["record"][h]["ens6np0"]["rdma_core"] for h in core] == [65, 65, 50]


def test_bw_report_explains_a_queue_pair_that_could_not_be_created():
    run = {"client": "a", "client_nic": "x", "server": "b", "server_nic": "x", "server_ip": "198.51.100.2",
           "gbps": None, "client_rdma_core": 50,
           "output": ["Couldn't create rdma old QP - Bad address", "Unable to create QP.", "Failed to create QP."]}
    assert _mod.rdma_bw_report([run], {}, 0.5)["errors"] == [
        "a x -> b x (198.51.100.2): ib_write_bw measured nothing: Couldn't create rdma old QP - Bad address "
        "Unable to create QP. Failed to create QP. a could not create an RDMA queue pair: its rdma-core (50) "
        "probably does not work with its kernel's RDMA driver; install a newer rdma-core on it"]
