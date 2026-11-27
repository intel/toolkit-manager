# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

# configure installs packages with sudo apt-get. sudo resets the environment, so a
# DEBIAN_FRONTEND exported by the script never reached apt, and a package that asks a
# question on first install (tzdata, pulled in by deadsnakes' python3.11) waited on
# the terminal while the progress dots kept printing.

import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "toolkit_manager.sh"


def test_apt_get_runs_noninteractive_even_though_sudo_resets_the_environment(tmp_path):
    (tmp_path / "apt-get").write_text('#!/bin/sh\necho "DEBIAN_FRONTEND=${DEBIAN_FRONTEND:-unset} $*"\n')
    (tmp_path / "apt-get").chmod(0o755)
    # A sudo that resets the environment, as sudo's default env_reset does.
    script = f'sudo() {{ env -i PATH="{tmp_path}:/usr/bin:/bin" "$@"; }}; export -f sudo; ' \
             f'source "{SCRIPT}"; bash -c "_apt_get install -y -qq tzdata"'
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "DEBIAN_FRONTEND=noninteractive install -y -qq tzdata"


def test_no_apt_get_call_bypasses_the_helper():
    assert "sudo apt-get" not in SCRIPT.read_text()
