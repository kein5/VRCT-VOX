"""Helpers for browser tests of settings pages with folded sections."""

import re

ENGINE_SETTINGS = re.compile("Engine settings|エンジン設定")


def open_engine_settings(page):
    """Engine settings start folded; open each one, as a user would, to reach its fields."""
    page.locator("summary").filter(has_text=ENGINE_SETTINGS).first.wait_for()
    closed = page.locator("details:not([open]) > summary").filter(has_text=ENGINE_SETTINGS)
    while closed.count():
        closed.first.click()
