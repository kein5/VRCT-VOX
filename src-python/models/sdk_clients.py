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
