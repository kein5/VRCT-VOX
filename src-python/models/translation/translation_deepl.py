"""Per-client DeepL limits without changing the SDK's process-wide defaults."""

from deepl.http_client import HttpClient

try:
    from .translation_timeouts import DEEPL_TIMEOUT
except ImportError:
    from translation_timeouts import DEEPL_TIMEOUT


class _RuntimeHttpClient(HttpClient):
    # DeepL 1.22 exposes neither a timeout nor a transport injection parameter
    # on DeepLClient/translate_text. Keep the private SDK adaptation here and
    # exercise it against the installed SDK with a fake requests session.
    def _internal_request(self, request, stream, **kwargs):
        kwargs["timeout"] = DEEPL_TIMEOUT
        return super()._internal_request(request, stream, **kwargs)

    def _should_retry(self, response, exception, num_retries):
        # Keep SDK retryable errors and backoff, but allow only one retry.
        return num_retries < 1 and super()._should_retry(response, exception, num_retries)


def configureDeepLRuntimeTimeout(client) -> None:
    """Install runtime limits after the existing credential probe succeeds.

    Both application construction sites use DeepLClient's default transport
    options. Close that probe transport before retaining the runtime one.
    """
    runtime_client = _RuntimeHttpClient()
    client._client.close()
    client._client = runtime_client
