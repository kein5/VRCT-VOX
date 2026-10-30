"""Serialize a Python warning as one stderr line for Tauri's line stream.

Keep category, message and location without suppressing warnings or touching
exception handling. JSON escapes embedded newlines in third-party messages.
"""
import json


def format_warning(message, category, filename, lineno, line=None):
    return json.dumps({"type": "vrct_warning", "category": category.__name__,
                       "message": str(message), "filename": filename,
                       "lineno": lineno}, ensure_ascii=False) + "\n"
