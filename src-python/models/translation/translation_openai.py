from models.diagnostics import provider_errors
from utils import errorLogging
from models.network_policy import without_tracing, chat_http_clients, fetch_openai_models, OPENAI_BASE_URL, validate_api_url
from models.sdk_clients import ChatOpenAI, OpenAI, SecretStr

try:
    from .translation_languages import translation_lang
    from .translation_utils import loadTranslatePromptConfig
    from .translation_model_list import RecentModelList
    from .translation_response import extractTranslationText
    from .translation_timeouts import CLOUD_LLM_TIMEOUT
except Exception:
    import sys
    from os import path as os_path
    sys.path.append(os_path.dirname(os_path.dirname(os_path.dirname(os_path.abspath(__file__)))))
    from translation_languages import translation_lang, loadTranslationLanguages
    from translation_utils import loadTranslatePromptConfig
    from translation_model_list import RecentModelList
    from translation_response import extractTranslationText
    from translation_timeouts import CLOUD_LLM_TIMEOUT
    translation_lang = loadTranslationLanguages(path=".", force=True)

@provider_errors("OpenAI")
def _fetch_models(api_key: str, base_url: str | None = None):
    """モデル一覧を取得する。成功すればキーは有効 (認証の確認を兼ねる)。失敗は例外。"""
    return fetch_openai_models(OpenAI, api_key, base_url if base_url is not None else OPENAI_BASE_URL)

def _text_models(res) -> list[str]:
    """Extract only GPT models suitable for translation and chat applications (plus those with fine-tuning)
    """
    allowed_models = []

    for model in res.data:
        model_id = model.id
        root = getattr(model, "root", "")

        # 除外対象のキーワード
        exclude_keywords = [
            "whisper",       # 音声認識
            "embedding",     # 埋め込み
            "image",         # 画像生成
            "tts",           # 音声合成
            "audio",         # 音声系（transcribe, diarize含む）
            "search",        # 検索補助モデル
            "transcribe",    # 音声→文字起こし
            "diarize",       # 話者分離
            "vision"         # 画像入力系（旧gpt-4-visionなど）
        ]

        # 除外キーワードが含まれているモデルをスキップ
        if any(kw in model_id for kw in exclude_keywords):
            continue

        # GPTモデルまたはFine-tune GPTモデルのみ対象
        if model_id.startswith("gpt-"):
            allowed_models.append(model_id)
        elif model_id.startswith("ft:") and root.startswith("gpt-"):
            allowed_models.append(model_id)

    allowed_models.sort()
    return allowed_models

@provider_errors("OpenAI")
def _get_available_text_models(api_key: str, base_url: str | None = None) -> list[str]:
    return _text_models(_fetch_models(api_key, base_url))

class OpenAIClient(RecentModelList):
    """OpenAI Translation simple wrapper.
    prompt/translation_openai.yml から system_prompt / supported_languages を読み込む。
    """
    provider_name = "OpenAI"

    @without_tracing
    def __init__(self, base_url: str | None = None, root_path: str = None):
        self.api_key = None
        self.model = None
        self.base_url = validate_api_url(base_url if base_url is not None else OPENAI_BASE_URL)

        prompt_config = loadTranslatePromptConfig(root_path, "translation_openai.yml")
        self.supported_languages = list(translation_lang["OpenAI_API"]["source"].keys())
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

    @provider_errors(lambda self, *args, **kwargs: self.provider_name)
    def getModelList(self) -> list[str]:
        if not self.api_key:
            return []
        return self._remember(self._takeAuthModels() or _get_available_text_models(self.api_key, self.base_url))

    def getAuthKey(self) -> str:
        return self.api_key

    @provider_errors(lambda self, *args, **kwargs: self.provider_name)
    def setAuthKey(self, api_key: str) -> bool:
        try:
            res = _fetch_models(api_key, self.base_url)
        except Exception:
            errorLogging(provider=self.provider_name)
            return False
        self.api_key = api_key
        self._rememberFromAuth(lambda: _text_models(res))
        return True

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
            **chat_http_clients(self.base_url, CLOUD_LLM_TIMEOUT),
            timeout=CLOUD_LLM_TIMEOUT,
            max_retries=1,
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

            # filter by source and take newest N
            filtered = [h for h in self._context_history if h.get("source") in allowed_sources]
            recent = filtered[-max_messages:] if max_messages > 0 else filtered
            # format items
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
            # truncate by char limit to mitigate token use
            if max_chars and len(history_blob) > max_chars:
                history_blob = history_blob[-max_chars:]
            # assemble header and append to system prompt
            history_header = header_tmpl.format(max_messages=max_messages, history=history_blob)
            if history_header:
                system_prompt = f"{system_prompt}\n\n{history_header}"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text},
        ]

        resp = self.openai_llm.invoke(messages)
        metadata = resp.response_metadata
        if (
            metadata.get("finish_reason") == "length"
            or (metadata.get("incomplete_details") or {}).get("reason") == "max_output_tokens"
        ):
            # ChatOpenAI selects the Responses API for some models (e.g. gpt-5-pro).
            # Discard partial output; Model.getTranslate uses the empty-translation failure path.
            return ""
        return extractTranslationText(resp.content)

if __name__ == "__main__":
    AUTH_KEY = input("OPENAI_API_KEY: ")
    client = OpenAIClient()
    client.setAuthKey(AUTH_KEY)
    models = client.getModelList()
    if models:
        print("Available models:", models)
        model = input("Select a model: ")
        client.setModel(model)
        client.updateClient()
        print(client.translate("こんにちは世界", "Japanese", "English"))
