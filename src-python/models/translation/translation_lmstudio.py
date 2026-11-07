from models.diagnostics import provider_errors
from utils import errorLogging
from models.network_policy import without_tracing, chat_http_clients, api_request, discovery, validate_api_url
from models.sdk_clients import ChatOpenAI, SecretStr

try:
    from .translation_languages import translation_lang
    from .translation_utils import loadTranslatePromptConfig
    from .translation_model_list import RecentModelList
    from .translation_response import extractTranslationText
    from .translation_timeouts import LOCAL_LLM_TIMEOUT
except Exception:
    import sys
    from os import path as os_path
    sys.path.append(os_path.dirname(os_path.abspath(__file__)))
    from translation_languages import translation_lang, loadTranslationLanguages
    from translation_utils import loadTranslatePromptConfig
    from translation_model_list import RecentModelList
    from translation_response import extractTranslationText
    from translation_timeouts import LOCAL_LLM_TIMEOUT
    translation_lang = loadTranslationLanguages(path=".", force=True)

@provider_errors("LMStudio")
@discovery
def _authentication_check(base_url: str | None = None) -> bool:
    """Check if the provided API key is valid by attempting to list models.
    """
    try:
        response = api_request("GET", f"{base_url}/models", timeout=0.2)
        if response.status_code == 200:
            return True
        else:
            return False
    except Exception:
        errorLogging(provider="LMStudio")
        return False

@provider_errors("LMStudio")
@discovery
def _get_available_text_models(base_url: str | None = None) -> list[str]:
    """Extract the list of available text models from the LM Studio.
    """
    try:
        response = api_request("GET", f"{base_url}/models", timeout=0.2)
        models = response.json()["data"]
    except Exception:
        errorLogging(provider="LMStudio")
        models = []

    allowed_models = []
    for model in models:
        allowed_models.append(model["id"])

    allowed_models.sort()
    return allowed_models

class LMStudioClient(RecentModelList):
    """LM Studio Translation simple wrapper.
    prompt/translation_lmstudio.yml から system_prompt / supported_languages を読み込む。
    """
    provider_name = "LMStudio"

    def __init__(self, base_url: str | None = None, root_path: str = None):
        self.api_key = "lmstudio"
        self.model = None
        self.base_url = validate_api_url(base_url if base_url is not None else "http://127.0.0.1:1234/v1")

        prompt_config = loadTranslatePromptConfig(root_path, "translation_lmstudio.yml")
        self.supported_languages = list(translation_lang["LMStudio"]["source"].keys())
        self.prompt_template = prompt_config["system_prompt"]
        # history config (optional)
        self.history_cfg = prompt_config.get("history", {
            "use_history": False,
            "sources": [],
            "max_messages": 0,
            "max_chars": 0,
            "header_template": "",
            "item_template": "[{source}] {role}: {text}",
        })
        self._context_history: list[dict] = []

        self.openai_llm = None

    def getBaseURL(self) -> str | None:
        return self.base_url

    def setBaseURL(self, base_url: str | None) -> None:
        result = _authentication_check(base_url=base_url)
        if result:
            self.base_url = base_url
        return result

    @provider_errors(lambda self, *args, **kwargs: self.provider_name)
    def getModelList(self) -> list[str]:
        return self._remember(_get_available_text_models(base_url=self.base_url)) if self.base_url else []

    def getModel(self) -> str:
        return self.model

    @provider_errors(lambda self, *args, **kwargs: self.provider_name)
    @without_tracing
    def updateClient(self) -> None:
        self.openai_llm = ChatOpenAI(
            base_url=self.base_url,
            model=self.model,
            api_key=SecretStr(self.api_key),
            streaming=False,
            **chat_http_clients(self.base_url, LOCAL_LLM_TIMEOUT),
            timeout=LOCAL_LLM_TIMEOUT,
            max_retries=0,
        )

    def setContextHistory(self, history_items: list[dict]) -> None:
        """Set recent conversation history for prompt injection.

        Each item should be a dict containing:
        - source: "chat" | "mic" | "speaker"
        - text: message string
        - timestamp: ISO format datetime string
        """
        self._context_history = history_items or []

    @provider_errors(lambda self, *args, **kwargs: self.provider_name)
    @without_tracing
    def translate(self, text: str, input_lang: str, output_lang: str) -> str:
        system_prompt = self.prompt_template.format(
            supported_languages=self.supported_languages,
            input_lang=input_lang,
            output_lang=output_lang,
        )

        # Inject recent conversation history if enabled by YAML config
        if self.history_cfg.get("use_history"):
            allowed_sources = set(self.history_cfg.get("sources", []))
            max_messages = int(self.history_cfg.get("max_messages", 0))
            max_chars = int(self.history_cfg.get("max_chars", 0))
            item_tmpl = self.history_cfg.get("item_template", "[{source}] {role}: {text}")
            header_tmpl = self.history_cfg.get("header_template", "{history}")

            filtered = [h for h in self._context_history if h.get("source") in allowed_sources]
            recent = filtered[-max_messages:] if max_messages > 0 else filtered
            formatted_items = []
            for h in recent:
                # Format timestamp as HH:MM to save tokens
                timestamp_str = ''
                if 'timestamp' in h:
                    from datetime import datetime
                    try:
                        ts = datetime.fromisoformat(h['timestamp'])
                        timestamp_str = ts.strftime('%H:%M')
                    except:
                        timestamp_str = ''
                formatted_items.append(
                    item_tmpl.format(
                        timestamp=timestamp_str,
                        source=h.get("source", ""),
                        text=h.get("text", ""),
                    )
                )
            history_blob = "\n".join(formatted_items).strip()
            if max_chars and len(history_blob) > max_chars:
                history_blob = history_blob[-max_chars:]
            history_header = header_tmpl.format(max_messages=max_messages, history=history_blob)
            if history_header:
                system_prompt = f"{system_prompt}\n\n{history_header}"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text},
        ]

        resp = self.openai_llm.invoke(messages)
        if resp.response_metadata.get("finish_reason") == "length":
            # Discard partial output; Model.getTranslate uses the empty-translation failure path.
            return ""
        return extractTranslationText(resp.content)

if __name__ == "__main__":
    client = LMStudioClient(base_url="http://127.0.0.1:1234/v1")
    models = client.getModelList()
    if models:
        print("Available models:", models)
        model = input("Select a model: ")
        client.setModel(model)
        client.updateClient()
        print(client.translate("こんにちは世界", "Japanese", "English"))
