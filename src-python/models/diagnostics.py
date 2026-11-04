"""Redacted general diagnostics and explicit provider exception boundaries."""

from functools import wraps
import re
import sys

from models.network_policy import redact_urls

_MASK = "***MASKED***"
_SECRET_NAME = re.compile(r"api_?keys?|auth_?(?:keys?|tokens?)|password|secret|token|credential", re.I)
_QUOTED_VALUE = r'"(?:\\.|[^"\\])*"' + "|" + r"'(?:\\.|[^'\\])*'"
_AUTHORIZATION = re.compile(
    r'''(?i)(["']?(?:proxy-)?authorization["']?\s*[:=]\s*)(?:'''
    + _QUOTED_VALUE + r"|[^\r\n,;}\]]+)")
_CREDENTIAL_FIELD = re.compile(
    r'''(?i)(?<![\w-])(["']?(?:x-goog-api-key|api[_-]?key|auth[_-]?(?:key|token)|access[_-]?token|refresh[_-]?token|key)["']?\s*[:=]\s*)(?:'''
    + _QUOTED_VALUE + r'''|[^\s,;&}\]"']+)''')
_BEARER = re.compile(r'''(?i)(\bBearer[ \t]+)[^\s'",;}\]]+''')


def _configured_secrets():
    # Do not import/initialize Config while logging a config-load failure.
    module = sys.modules.get("config")
    config = getattr(module, "config", None)
    if config is None:
        config = getattr(getattr(module, "Config", None), "_instance", None)
    secrets = set()

    def collect(value, sensitive=False):
        if isinstance(value, dict):
            for key, item in list(value.items()):
                collect(item, sensitive or bool(_SECRET_NAME.search(str(key))))
        elif isinstance(value, (list, tuple)):
            for item in value:
                collect(item, sensitive)
        elif sensitive and isinstance(value, str) and value:
            secrets.add(value)

    collect(vars(config) if config is not None else {})
    return secrets


def redact_diagnostic_text(text):
    """Keep useful messages, masking configured secrets, URLs and credentials."""
    for secret in sorted(_configured_secrets(), key=len, reverse=True):
        text = text.replace(secret, _MASK)
    text = redact_urls(text)
    for pattern in (_AUTHORIZATION, _CREDENTIAL_FIELD, _BEARER):
        text = pattern.sub(lambda match: match[1] + _MASK, text)
    return text


_PROVIDER_MODULES = (
    "openai", "groq", "deepl", "google.genai", "google.api_core",
    "langchain_openai", "langchain_groq", "langchain_google_genai", "ollama",
    "speech_recognition",
)


def exception_provider(exception):
    """Recognize marked calls and SDK exceptions, including wrapped failures."""
    pending = [exception]
    seen = set()
    while pending:
        exc = pending.pop()
        if exc is None or id(exc) in seen:
            continue
        seen.add(id(exc))
        provider = getattr(exc, "_vrct_provider", None)
        if provider is not None:
            return provider
        for cls in type(exc).__mro__:
            for module in _PROVIDER_MODULES:
                if cls.__module__ == module or cls.__module__.startswith(module + "."):
                    return module
        pending.extend((exc.__cause__, exc.__context__))
    return None


def provider_errors(provider):
    """Mark escaping provider failures so outer general handlers stay safe.

    Preserve the original exception type and error mapping. Logging at this
    boundary also covers direct adapter callers and response parsing errors.
    """
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            try:
                return function(*args, **kwargs)
            except Exception as exc:
                if getattr(exc, "_vrct_provider", None) is None:
                    name = provider(*args, **kwargs) if callable(provider) else provider
                    from utils import errorLogging
                    errorLogging(provider=name)
                raise
        return wrapped
    return decorate
