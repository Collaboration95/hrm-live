"""HRM Live UI package.

UI modules use rumps (AppKit) on the main thread and read shared state
for display. They never import bleak or run asyncio code.
"""
