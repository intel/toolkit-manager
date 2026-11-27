# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

# Roles shell out to jq (llm_services' model deploy, nri_cpu_balloons' CPU sizing), so
# configure installs it with the other host tools; a fresh host without it failed the
# install at the model-deploy step.

import os
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "toolkit_manager.sh"
STEPS = ["_configure_debian", "_configure_locale", "_install_yq", "_install_jq",
         "_install_kubectl", "_install_helm", "_ensure_venv"]


def test_configure_installs_jq_with_the_other_host_tools():
    stubs = "; ".join(f"{s}() {{ echo {s}; }}" for s in STEPS)
    script = (f'source "{SCRIPT}"; {stubs}; confirm() {{ :; }}; sudo() {{ :; }}; '
              '_detect_os() { echo debian; }; configure 2>/dev/null')
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True)
    assert [line for line in out.stdout.split() if line in STEPS] == STEPS


def test_install_jq_downloads_the_pinned_release_for_this_arch(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in ("mktemp", "rm", "uname", "cp", "chmod", "sleep", "cat"):
        os.symlink(subprocess.run(["bash", "-c", f"command -v {tool}"], capture_output=True,
                                  text=True, check=True).stdout.strip(), bin_dir / tool)
    url = tmp_path / "url"
    script = (f'source "{SCRIPT}"; PATH="{bin_dir}"; '
              f'_download() {{ echo "$1" > "{url}"; printf "#!/bin/sh\\necho jq-1.8.2\\n" > "$2"; }}; '
              f'sudo() {{ cp "$4" "{bin_dir}/jq"; chmod 755 "{bin_dir}/jq"; }}; '
              '_arch() { echo amd64; }; _install_jq')
    subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True)
    assert url.read_text().strip() == ("https://github.com/jqlang/jq/releases/download/"
                                       "jq-1.8.2/jq-linux-amd64")
