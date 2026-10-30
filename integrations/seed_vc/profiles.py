# SPDX-License-Identifier: GPL-3.0-only
"""Experiment settings; none imply quality or latency acceptance."""
PROFILES = {
    'baseline': {'block_time': .25, 'extra_time_right': 2.0},
    'author': {'block_time': .18, 'extra_time_right': .02},
    'low': {'block_time': .08, 'extra_time_right': .02},
}
