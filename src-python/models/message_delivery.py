"""Source ownership for work that may outlive a mute or a bounded stop."""

from threading import Lock


class DeliveryEpochs:
    def __init__(self):
        self._lock = Lock()
        self._epochs = dict.fromkeys(("mic", "speaker", "ocr", "chat"), 0)

    def snapshot(self, source):
        with self._lock:
            return self._epochs[source]

    def current(self, source, epoch):
        with self._lock:
            return self._epochs[source] == epoch

    def revoke(self, source):
        # Never hold this lock across rendering, publication or worker joins.
        with self._lock:
            self._epochs[source] += 1
