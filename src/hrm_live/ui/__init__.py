"""HRM Live UI package.

UI modules use rumps (AppKit) on the main thread and read shared state
for display. They do not load the BLE stack or run asyncio code.
"""
