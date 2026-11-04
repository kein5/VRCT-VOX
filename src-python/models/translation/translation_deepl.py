"""Per-client DeepL limits without changing the SDK's process-wide defaults."""

from models.diagnostics import provider_errors

from deepl.http_client import HttpClient
from models.network_policy import DISCOVERY_TIMEOUT, discovery_scope, own_discovery_client, check_discovery_deadline, explicit_request_auth

try:
    from .translation_timeouts import DEEPL_TIMEOUT
except ImportError:
    from translation_timeouts import DEEPL_TIMEOUT


class _RuntimeHttpClient(HttpClient):
    # DeepL 1.22 exposes neither a timeout nor a transport injection parameter
    # on DeepLClient/translate_text. Keep the private SDK adaptation here and
    # exercise it against the installed SDK with a fake requests session.
    def __init__(self):
        super().__init__()
        self._session.auth = explicit_request_auth

    def _internal_request(self, request, stream, **kwargs):
        check_discovery_deadline()
        kwargs["timeout"] = DEEPL_TIMEOUT
        kwargs["allow_redirects"] = False
        return super()._internal_request(request, stream, **kwargs)

    def _should_retry(self, response, exception, num_retries):
        # Keep SDK retryable errors and backoff, but allow only one retry.
        return num_retries < 1 and super()._should_retry(response, exception, num_retries)


def configureDeepLRuntimeTimeout(client) -> None:
    """Close the authentication transport before retaining runtime limits."""
    runtime_client = _RuntimeHttpClient()
    client._client.close()
    client._client = runtime_client


class _DiscoveryHttpClient(_RuntimeHttpClient):
    def _internal_request(self, request, stream, **kwargs):
        check_discovery_deadline()
        return HttpClient._internal_request(self, request, stream,
                                            timeout=(DISCOVERY_TIMEOUT, DISCOVERY_TIMEOUT),
                                            allow_redirects=False)

    def _should_retry(self, response, exception, num_retries):
        return False


@provider_errors("DeepL")
def authenticateDeepL(client_type, auth_key):
    """Bind the official host and close the short-lived authentication transport."""
    base_url = "https://api-free.deepl.com" if auth_key.endswith(":fx") else "https://api.deepl.com"
    client = client_type(auth_key, server_url=base_url)
    client._client.close()
    with discovery_scope():
        client._client = own_discovery_client(_DiscoveryHttpClient())
        client.translate_text(" ", target_lang="EN-US")
    configureDeepLRuntimeTimeout(client)
    return client
