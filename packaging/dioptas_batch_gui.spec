"""PyInstaller specification for the standalone desktop application."""

from __future__ import annotations

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, copy_metadata


PROJECT_ROOT = Path(SPECPATH).parent
ASSETS_DIR = PROJECT_ROOT / "dioptas_batch_gui" / "assets"

datas = [(str(PROJECT_ROOT / "LICENSE"), ".")]
binaries = []
hiddenimports = []


def include_runtime_submodule(module_name):
    """Exclude package tests and benchmarks from end-user builds."""
    ignored_parts = {"test", "tests", "benchmark", "benchmarks"}
    return ignored_parts.isdisjoint(module_name.split("."))


# These scientific packages use runtime-loaded backends, codecs, and Qt
# resources that static analysis cannot discover reliably.
for package_name in ("dioptas", "fabio", "pyFAI", "silx", "hdf5plugin"):
    package_datas, package_binaries, package_hiddenimports = collect_all(
        package_name,
        filter_submodules=include_runtime_submodule,
        exclude_datas=["**/test/**", "**/tests/**", "**/benchmark/**", "**/benchmarks/**"],
    )
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hiddenimports
    datas += copy_metadata(package_name)

analysis = Analysis(
    [str(PROJECT_ROOT / "packaging" / "launcher.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "IPython", "notebook", "jupyterlab"],
    noarchive=False,
)

pyz = PYZ(analysis.pure)

icon_path = ASSETS_DIR / ("dbg.icns" if sys.platform == "darwin" else "dbg.ico")

executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="DioptasBatchGUI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(icon_path),
)

application = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="DioptasBatchGUI",
)

if sys.platform == "darwin":
    bundle = BUNDLE(
        application,
        name="Dioptas Batch GUI.app",
        icon=str(icon_path),
        bundle_identifier="org.shdshim.dioptas-batch-gui",
        info_plist={
            "CFBundleDisplayName": "Dioptas Batch GUI",
            "CFBundleName": "Dioptas Batch GUI",
            "NSHighResolutionCapable": True,
        },
    )
