"""py2app build configuration for HRM Live.app.

Build command:
    python setup.py py2app

The .app bundle will be created in dist/HRM Live.app.
"""

from __future__ import annotations

import subprocess
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from setuptools import setup

try:
    from py2app.build_app import py2app
except ImportError:
    py2app = None  # type: ignore[assignment]

APP = ["src/hrm_live/__main__.py"]
APP_NAME = "HRM Live"
ENTITLEMENTS = Path("hrm-live.entitlements")
PACKAGE_NAME = "hrm-bar"

DATA_FILES = []

OPTIONS = {
    "argv_emulation": False,
    "plist": {
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleIdentifier": "com.hrmlive.app",
        "CFBundleVersion": "0.1.0",
        "CFBundleShortVersionString": "0.1.0",
        "NSBluetoothAlwaysUsageDescription": (
            "HRM Live uses Bluetooth to connect to your heart rate "
            "monitor strap and display live BPM data."
        ),
        "NSBluetoothPeripheralUsageDescription": (
            "HRM Live uses Bluetooth to connect to your heart rate monitor strap."
        ),
        "NSHumanReadableCopyright": "MIT License",
        "LSUIElement": True,  # No dock icon (menu bar only)
    },
    "packages": [
        "rumps",
        "bleak",
        "matplotlib",
        "hrm_live",
        "hrm_live.ui",
    ],
    "includes": [
        "AppKit",
        "CoreBluetooth",
        "Foundation",
        "matplotlib.backends.backend_agg",
    ],
    "excludes": [
        "PyObjCTest",
        "test",
        "tests",
        "tkinter",
        "PIL",
    ],
    "matplotlib_backends": ["agg"],
    "site_packages": True,
    "iconfile": None,  # Use a default icon; can be set later
    "emulate_shell_environment": True,
    "resources": [],
}


class Py2AppWithEntitlements(py2app if py2app is not None else object):
    """Build the app and ad-hoc sign it with Bluetooth entitlements."""

    def finalize_options(self):
        if py2app is None:
            raise RuntimeError("Install the build extra before running py2app.")
        self.distribution.install_requires = None
        super().finalize_options()

    def run(self):
        if py2app is None:
            raise RuntimeError("Install the build extra before running py2app.")
        super().run()
        app_path = Path(self.dist_dir) / f"{APP_NAME}.app"
        if not app_path.exists():
            raise RuntimeError(f"Expected app bundle was not created: {app_path}")
        if not ENTITLEMENTS.exists():
            raise RuntimeError(f"Missing entitlements file: {ENTITLEMENTS}")
        subprocess.run(
            [
                "codesign",
                "--force",
                "--deep",
                "--sign",
                "-",
                "--entitlements",
                str(ENTITLEMENTS),
                str(app_path),
            ],
            check=True,
        )


def _version_plist() -> dict[str, str]:
    """Derive bundle version values from installed project metadata."""

    try:
        app_version = version(PACKAGE_NAME)
    except PackageNotFoundError:
        app_version = "0.1.0"
    return {
        "CFBundleVersion": app_version,
        "CFBundleShortVersionString": app_version,
    }


setup(
    name=APP_NAME,
    app=APP,
    data_files=DATA_FILES,
    options={"py2app": {**OPTIONS, "plist": {**OPTIONS["plist"], **_version_plist()}}},
    cmdclass={"py2app": Py2AppWithEntitlements},
)
