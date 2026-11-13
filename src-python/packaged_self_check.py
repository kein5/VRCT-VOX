"""`vrct-vox-sidecar --self-check`: can this build load what it loads only when a feature turns on?

A package is built and inspected file by file, but libraries that are imported lazily are
first touched when the user presses a switch. One of them (Transformers, for the local
translation's tokenizer) could not be imported from any Windows package up to 0.1.0-beta.7,
and nothing noticed. The build runs this check on the packaged backend itself.

No model, device or network is used: each check only imports what the feature imports.
The output names libraries and exception types, never paths or messages.
"""
import sys


def _translation_tokenizer():
    # The attribute lookups are the lazy imports that failed inside the PYZ archive.
    import transformers
    return transformers.M2M100Tokenizer, transformers.NllbTokenizerFast


def _translation_engine():
    import ctranslate2
    import sentencepiece
    return ctranslate2.Translator, sentencepiece.SentencePieceProcessor


def _whisper():
    from faster_whisper import WhisperModel
    return WhisperModel


CHECKS = (
    ("translation tokenizer (transformers)", _translation_tokenizer),
    ("translation engine (ctranslate2, sentencepiece)", _translation_engine),
    ("speech recognition (faster-whisper)", _whisper),
)


def run(checks=CHECKS, out=None):
    """Runs every check; returns the names of those that failed."""
    out = sys.stdout if out is None else out
    failed = []
    for name, check in checks:
        try:
            check()
        except BaseException as error:  # An ImportError or anything a library raises while loading.
            failed.append(name)
            print(f"FAILED {name}: {type(error).__name__}", file=out, flush=True)
        else:
            print(f"ok {name}", file=out, flush=True)
    return failed


def main():
    failed = run()
    print("self-check " + ("failed" if failed else "passed"), flush=True)
    return 1 if failed else 0
