"""Helpers for browser tests of settings pages with folded sections."""


def open_engine_settings(page):
    """One-time setup (models, runtimes, servers) starts folded; open it, as a user would, to reach its fields."""
    page.locator("details[data-setup] > summary").first.wait_for()
    closed = page.locator("details[data-setup]:not([open]) > summary")
    while closed.count():
        closed.first.click()


open_setup = open_engine_settings
