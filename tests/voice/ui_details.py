"""Helpers for browser tests of settings pages with folded sections."""

import re

SETUP = re.compile("Models and servers|モデルとサーバー")


def open_engine_settings(page):
    """Model and server setup starts folded; open it, as a user would, to reach its fields."""
    page.locator("summary").filter(has_text=SETUP).first.wait_for()
    closed = page.locator("details:not([open]) > summary").filter(has_text=SETUP)
    while closed.count():
        closed.first.click()
