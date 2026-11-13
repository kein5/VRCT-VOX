"""Source ownership for work that may outlive a mute or a bounded stop."""

from threading import Lock


class DeliveryEpochs:
    def __init__(self):
        self._lock = Lock()
        self._epochs = dict.fromkeys(("mic", "speaker", "ocr", "chat"), 0)
        self._closed = False

    def snapshot(self, source):
        with self._lock:
            return None if self._closed else self._epochs[source]

    def current(self, source, epoch):
        with self._lock:
            return not self._closed and self._epochs[source] == epoch

    def close(self):
        with self._lock:
            self._closed = True

    def revoke(self, source):
        # Never hold this lock across rendering, publication or worker joins.
        with self._lock:
            self._epochs[source] += 1


class ChatboxOrder:
    """Only successful sends advance the shared chatbox watermark."""

    def __init__(self):
        self._lock = Lock()
        self._sequence = 0
        self._sent = 0

    def admit(self):
        with self._lock:
            self._sequence += 1
            return self._sequence

    def send(self, sequence, publish, current):
        # Serialize the comparison and OSC call, not translation or other sinks.
        with self._lock:
            if not current():
                return
            if sequence < self._sent:
                return False
            if publish() is False:
                return
            self._sent = sequence
            return True
