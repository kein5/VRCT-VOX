"""Runtime transport limits; startup credential checks keep their own budget.

HTTP timeouts bound I/O waits, not the wall time of a whole translation (a
peer can keep sending data). Do not implement these with disposable workers.
"""

from httpx import Timeout


# Cloud chat should fail over promptly; local servers may need to load weights.
CLOUD_LLM_TIMEOUT_SECONDS = 30.0
CLOUD_LLM_TIMEOUT = Timeout(CLOUD_LLM_TIMEOUT_SECONDS, connect=5.0, write=10.0, pool=5.0)
LOCAL_LLM_TIMEOUT = Timeout(120.0, connect=5.0, write=10.0, pool=5.0)
# DeepL's existing read timeout is sufficient for short chat messages.
DEEPL_TIMEOUT = (5.0, 10.0)
