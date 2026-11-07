"""Provider SDKs, loaded when a client is built instead of at startup.

Importing openai, langchain and google-genai takes about three seconds, and a
default setup uses none of them. These functions keep the names and call
signatures of the SDK classes, so a client module only changes its import line.

The imports stay plain statements inside the functions: PyInstaller finds them
that way.
"""


def OpenAI(*args, **kwargs):
    from openai import OpenAI as client
    return client(*args, **kwargs)


def ChatOpenAI(*args, **kwargs):
    from langchain_openai import ChatOpenAI as client
    return client(*args, **kwargs)


def ChatOllama(*args, **kwargs):
    from langchain_ollama import ChatOllama as client
    return client(*args, **kwargs)


def ChatGoogleGenerativeAI(*args, **kwargs):
    from langchain_google_genai import ChatGoogleGenerativeAI as client
    return client(*args, **kwargs)


def SecretStr(value):
    from pydantic import SecretStr as secret
    return secret(value)


class _Genai:
    """The part of the google.genai module that the clients use."""

    @staticmethod
    def Client(*args, **kwargs):
        from google import genai as module
        return module.Client(*args, **kwargs)


genai = _Genai()


_OPENAI_STYLE_ENGINES = frozenset({"OpenAI_API", "OpenAI_Compatible", "Groq_API", "OpenRouter_API", "Plamo_API",
                                   "Groq_Whisper", "OpenAI_Whisper", "Custom_Whisper"})


def preloadSavedEngines(*auth_keys):
    """Import the SDKs that the saved keys will use during startup.

    Controller.init() checks every saved key within a time limit. On a busy PC the
    imports alone can use that limit up, and the engine would start unavailable.
    Without a saved key this does nothing, which is the common case.
    """
    engines = {engine for keys in auth_keys for engine, key in keys.items() if key}
    try:
        if engines & _OPENAI_STYLE_ENGINES:
            import langchain_openai  # noqa: F401
            import openai  # noqa: F401
        if "Gemini_API" in engines:
            from google import genai as _module  # noqa: F401
            import langchain_google_genai  # noqa: F401
    except Exception:
        # The client that needs the SDK reports this through its own path.
        pass
