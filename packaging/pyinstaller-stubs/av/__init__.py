"""Stand-in for PyAV in VRCT-VOX builds; the real package is not distributed.

PyAV's binary wheels bundle FFmpeg together with the GPL-licensed x264 and x265
encoders. faster-whisper imports `av` only to decode audio files, and VRCT-VOX
always passes decoded PCM (numpy arrays), so decoding is never reached. Placing
this package first on the PyInstaller search path keeps the real one (and its
native libraries) out of the frozen backend while `import av` still succeeds.
"""


def __getattr__(name):
    raise AttributeError(f"PyAV ({name}) is not included in VRCT-VOX builds")
