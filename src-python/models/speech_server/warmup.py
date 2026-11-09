"""One discarded request after an owned GPU server comes up.

With an empty driver cache, a server's first real sentence or caption waits for the
driver to build its kernels. Doing that here keeps the first one from being lost.
No microphone, router or queue is involved, and the result is thrown away. A warm-up
that fails only means the first real request is slow, so it never stops the server.
"""
import http.client
import io
import random
import socket
from urllib.parse import urlsplit
import uuid
import wave

from models.http_stream import InterruptibleSocket
from models.tts.speechcpp_tts import SpeechCppTTS, SpeechError

# Measured on an RTX 3060 Ti with an empty cache: "あ。" took 0.08 s and the next
# sentence still waited 8 s. A sentence of this length took 8 s, and every length after it under 1 s.
TEXT = 'こんにちは、今日はよろしくお願いします。'
# Likewise: 2 s of noise took 1.5 s and warmed nothing. 6 s took 8.3 s, and real speech then took 0.08 s.
NOISE_SECONDS = 6
RATE = 16000


def noise_wav():
    rng = random.Random(0)
    pcm = bytearray()
    for _ in range(NOISE_SECONDS * RATE):
        pcm += int(rng.gauss(0, 1800)).to_bytes(2, 'little', signed=True)
    out = io.BytesIO()
    with wave.open(out, 'wb') as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(RATE)
        writer.writeframes(bytes(pcm))
    return out.getvalue()


def _on_gpu(models, task):
    """The id of the model doing `task`, if it runs somewhere that has kernels to build."""
    try:
        return next(row['id'] for row in models
                    if row['speech']['task'] == task and row['speech'].get('device', 'CPU').lower() != 'cpu')
    except (KeyError, TypeError, StopIteration):
        return None


def _speak(base_url, token, limit):
    for _frame in SpeechCppTTS(base_url, first_audio_timeout=limit).synthesize_stream(TEXT, 'none', 'ja', token):
        token.check()
    return True


def _transcribe(base_url, name, token, limit):
    url = urlsplit(base_url)
    boundary = uuid.uuid4().hex
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="model"\r\n\r\n{name}\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="noise.wav"\r\n'
            'Content-Type: audio/wav\r\n\r\n').encode() + noise_wav() + f'\r\n--{boundary}--\r\n'.encode()
    connection = http.client.HTTPConnection(url.hostname, url.port, timeout=limit)
    try:
        connection.connect()
        sock = connection.sock = InterruptibleSocket(connection.sock)

        def interrupt():
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

        token.register(interrupt)
        token.check()
        connection.request('POST', '/v1/audio/transcriptions', body,
                           {'Content-Type': f'multipart/form-data; boundary={boundary}'})
        response = connection.getresponse()
        response.read(4096)
        token.check()
        return response.status == 200
    finally:
        connection.close()


def warm_up(profile, base_url, models, token, limit):
    """Whether a warm-up ran. Other profiles have no voice known to be accepted."""
    if limit <= 0 or token.is_set():
        return False
    try:
        if profile == 'japanese' and _on_gpu(models, 'synthesis'):
            return _speak(base_url, token, limit)
        if profile == 'asr' and (name := _on_gpu(models, 'recognition')):
            return _transcribe(base_url, name, token, limit)
    except (SpeechError, OSError, http.client.HTTPException):
        pass
    return False
