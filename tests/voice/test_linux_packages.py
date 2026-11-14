"""deb and rpm packages from a Linux candidate (tools/linux_packages.py).

dpkg-deb and rpmbuild run in the Linux candidate workflow, which also installs both packages in
clean containers (tools/ci/check_linux_package.sh). These tests cover what is decided in Python.
"""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import linux_packages as lp  # noqa: E402


@pytest.fixture
def candidate(tmp_path):
    root = tmp_path / "VRCT-VOX"
    (root / "_internal").mkdir(parents=True)
    (root / "vrct-vox").write_bytes(b"\x7fELF main")
    (root / "vrct-vox-sidecar").write_bytes(b"\x7fELF sidecar")
    (root / "_internal/libexample.so").write_bytes(b"\x7fELF lib")
    manifest = {"version": "0.3.0-beta.1", "variant": "linux-x64-vulkan", "files": [
        {"path": "vrct-vox", "elf_versions": ["GLIBC_2.34", "GLIBC_2.39", "GLIBCXX_3.4.32"]},
        {"path": "_internal/libexample.so", "elf_versions": ["GLIBC_2.17"]},
        {"path": "_internal/data.json"},
    ]}
    (root / "build-manifest.json").write_text(json.dumps(manifest))
    return root


@pytest.mark.parametrize("version,expected", [("0.3.0", "0.3.0"), ("0.3.0-beta.1", "0.3.0~beta.1"),
                                              ("10.2.11-beta.12", "10.2.11~beta.12")])
def test_package_versions_sort_a_beta_before_its_release(version, expected):
    assert lp.package_version(version) == expected


@pytest.mark.parametrize("version", ["0.3", "0.3.0-rc.1", "0.3.0-beta.0", "v0.3.0", "0.3.0\n"])
def test_other_versions_are_refused(version):
    with pytest.raises(ValueError):
        lp.package_version(version)


def test_the_lowest_glibc_is_the_highest_version_any_file_needs(candidate):
    assert lp.build_facts(candidate) == ("0.3.0-beta.1", "linux-x64-vulkan", "2.39")


def test_a_candidate_without_glibc_records_is_refused(candidate):
    manifest = json.loads((candidate / "build-manifest.json").read_text())
    manifest["files"] = [{"path": "vrct-vox"}]
    (candidate / "build-manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="glibc"):
        lp.build_facts(candidate)


def control_fields(control):
    return dict(line.split(": ", 1) for line in control.splitlines() if line and not line.startswith(" "))


def test_the_deb_declares_glibc_gtk_webkit_and_the_vulkan_loader():
    control = lp.deb_control("0.3.0-beta.1", "linux-x64-vulkan", "2.39", 1234)
    fields = control_fields(control)
    assert fields["Package"] == "vrct-vox"
    assert fields["Version"] == "0.3.0~beta.1"
    assert fields["Architecture"] == "amd64"
    assert fields["Installed-Size"] == "1234"
    assert fields["Depends"] == "libc6 (>= 2.39), libwebkit2gtk-4.1-0, libgtk-3-0t64 | libgtk-3-0, libvulkan1"
    assert fields["Recommends"] == "pipewire-bin, mesa-vulkan-drivers"
    assert "@" not in fields["Maintainer"]  # No personal address in published metadata.
    assert control.endswith("\n")


def test_the_cpu_variant_needs_no_vulkan():
    fields = control_fields(lp.deb_control("0.3.0", "linux-x64-cpu", "2.39", 1))
    assert "vulkan" not in fields["Depends"] + fields["Recommends"]
    assert "vulkan" not in lp.rpm_spec("0.3.0", "linux-x64-cpu", "2.39", "/staged")


def test_the_rpm_takes_the_files_as_built_and_declares_its_requirements(tmp_path):
    spec = lp.rpm_spec("0.3.0-beta.1", "linux-x64-vulkan", "2.39", tmp_path / "staged root")
    assert "Version: 0.3.0~beta.1" in spec
    assert "AutoReqProv: no" in spec  # The bundled libraries are not offered to other packages.
    assert "%global __os_install_post %{nil}" in spec  # Nothing is stripped or rewritten.
    for line in ("Requires: glibc >= 2.39", "Requires: webkit2gtk4.1", "Requires: gtk3", "Requires: vulkan-loader",
                 "Recommends: pipewire-utils", "Recommends: mesa-vulkan-drivers"):
        assert line in spec.splitlines()
    assert f"cp -al '{tmp_path / 'staged root'}/.'" in spec  # Hard links: no second 1 GB copy.


@pytest.mark.parametrize("kind", ["deb", "rpm"])
def test_the_installed_tree_has_the_app_under_opt_and_the_desktop_files_under_usr(candidate, tmp_path, kind):
    root = lp.stage(candidate, tmp_path / "root", kind)
    app = root / "opt/vrct-vox"
    assert (app / "vrct-vox").read_bytes() == b"\x7fELF main"
    assert (app / "_internal/libexample.so").is_file()
    assert (app / "package-manager").read_text() == kind + "\n"
    assert (root / "usr/bin/vrct-vox").read_text() == '#!/bin/sh\nexec /opt/vrct-vox/vrct-vox "$@"\n'
    desktop = (root / "usr/share/applications/vrct-vox.desktop").read_text()
    assert "Exec=vrct-vox" in desktop and "Icon=vrct-vox" in desktop
    assert (root / "usr/share/icons/hicolor/256x256/apps/vrct-vox.png").read_bytes()[:4] == b"\x89PNG"
    assert (root / "usr/share/doc/vrct-vox/copyright").read_text().startswith("MIT License")
    assert (root / "usr/share/doc/vrct-vox/NOTICE.md").is_file()


def test_a_folder_that_is_not_a_candidate_is_refused(tmp_path):
    (tmp_path / "empty").mkdir()
    with pytest.raises(ValueError, match="candidate"):
        lp.stage(tmp_path / "empty", tmp_path / "root", "deb")
