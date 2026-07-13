"""
py2app build configuration for HRM Live.app

Build command:
    python setup.py py2app

The .app bundle will be created in dist/HRM Live.app.
"""

import subprocess
from pathlib import Path

from py2app.build_app import py2app
from setuptools import setup

APP = ["app.py"]
APP_NAME = "HRM Live"
ENTITLEMENTS = Path("hrm-live.entitlements")

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
            "HRM Live uses Bluetooth to connect to your heart rate "
            "monitor strap."
        ),
        "NSHumanReadableCopyright": "MIT License",
        "LSUIElement": True,  # No dock icon (menu bar only)
    },
    "packages": [
        "rumps",
        "bleak",
        "matplotlib",
        "ui",
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


class Py2AppWithEntitlements(py2app):
    """Build the app and ad-hoc sign it with Bluetooth entitlements."""

    def finalize_options(self):
        self.distribution.install_requires = None
        super().finalize_options()

    def run(self):
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

setup(
    name=APP_NAME,
    app=APP,
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    cmdclass={"py2app": Py2AppWithEntitlements},
)
