"""A temporary file next to its target, for writing it and then replacing the target."""
import errno
import os
import secrets

# The same flags tempfile.mkstemp uses: a new file only, not inherited by children.
_FLAGS = (os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
          | getattr(os, "O_NOINHERIT", 0) | getattr(os, "O_BINARY", 0))
_ATTEMPTS = 100


def mkstemp(dir: str, prefix: str = "", suffix: str = "") -> tuple:
    """Like tempfile.mkstemp (an fd open for writing, mode 0600), but a refused write fails at once.

    On Windows, tempfile.mkstemp takes PermissionError for a name taken by a folder and tries
    another name while os.access says the folder is writable. That check reads only the read-only
    attribute, so when the folder's permissions or Controlled folder access refuse the write it
    kept retrying, up to about 2**31 times, and froze whatever waited for it. Here only a name
    that is already taken (FileExistsError) is retried.
    """
    for _ in range(_ATTEMPTS):
        path = os.path.join(dir, f"{prefix}{secrets.token_hex(6)}{suffix}")
        try:
            return os.open(path, _FLAGS, 0o600), path
        except FileExistsError:
            continue
    raise FileExistsError(errno.EEXIST, "No usable temporary file name found", dir)
