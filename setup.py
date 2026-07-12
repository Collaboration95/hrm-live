"""
py2app build configuration for HRM Live.app

Build command:
    python setup.py py2app

The .app bundle will be created in dist/HRM Live.app.
"""

from setuptools import setup

APP = ["app.py"]
APP_NAME = "HRM Live"

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
        "Quartz",
        "Foundation",
        "matplotlib.backends.backend_agg",
    ],
    "excludes": [
        "PyObjCTest",
        "test",
        "tests",
        "tkinter",
    ],
    "site_packages": True,
    "iconfile": None,  # Use a default icon; can be set later
    "emulate_shell_environment": True,
    "resources": [],
    "entitlements": "hrm-live.entitlements",
}

setup(
    name=APP_NAME,
    app=APP,
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
    install_requires=[
        "rumps>=0.4.0",
        "bleak>=0.21.0",
        "matplotlib>=3.8.0",
        "pyobjc-core",
        "pyobjc-framework-Cocoa",
    ],
)
