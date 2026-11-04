"""OpenAI互換の音声書き起こしAPI (Groq/OpenAI公式/カスタムサーバー) 向けの
認証キー検証・モデル一覧取得ヘルパー。

翻訳側の `models/translation/translation_openai_compatible.py` と同じ
「`client.models.list()` が成功するかどうかでキーの有効性を判定する」
方式 (実際に文字起こしを1回試すより軽量で、起動時の検証に向く)。

「文字起こし可能かどうか」を厳密に判定するのは難しい(実際の音声・
言語次第で結果が変わる)ため、「このキーでモデル一覧を取得できるか」を
可用性の代理指標として使う。
"""

from models.diagnostics import provider_errors
from utils import errorLogging

from openai import OpenAI
from models.network_policy import fetch_openai_models

# OpenAICompatibleTranscriptionProvider を base_url/model の差し替えだけで
# 使い回す3つのユーザー向けエンジン名。transcription_transcriber.py と
# controller.py の双方から参照される唯一の定義元。
TRANSCRIPTION_API_ENGINES = ("Groq_Whisper", "OpenAI_Whisper", "Custom_Whisper")

# Groq/OpenAI公式のモデル一覧には文字起こし以外のモデル(chat/embedding等)も
# 混在するため、モデル名にこれらのキーワードを含むものだけに絞り込む。
# "whisper" は Groq/OpenAI 双方の Whisper 系モデル名 (例: whisper-large-v3,
# whisper-1, distil-whisper-large-v3-en) をカバーし、"transcribe" は
# OpenAI の非Whisper系文字起こしモデル (例: gpt-4o-transcribe,
# gpt-4o-mini-transcribe) をカバーする。カスタムサーバーはどんなモデル名を
# 使っているか分からないため、呼び出し側でこのフィルタを適用しない。
TRANSCRIPTION_MODEL_KEYWORDS = ["whisper", "transcribe"]

# Speaker diarization models (e.g. gpt-4o-transcribe-diarize) answer a
# different question and need `chunking_strategy` for longer audio; they are
# left out of the filtered lists.
TRANSCRIPTION_MODEL_EXCLUDED_KEYWORDS = ["diarize"]


def transcriptionResponseFormat(model: str) -> str:
    """`/audio/transcriptions` に渡す response_format。

    OpenAI の gpt-*-transcribe 系 (gpt-4o-transcribe, gpt-4o-mini-transcribe
    等) は API リファレンス上 `json` しか受け付けず、`verbose_json` を送ると
    400 になる。Whisper 系 (Groq/OpenAI の whisper-*、カスタムサーバー) は
    セグメントと検出言語を返す `verbose_json` を使う。
    """
    name = model.lower()
    if "transcribe" in name and "whisper" not in name:
        return "json"
    return "verbose_json"


@provider_errors("OpenAI-compatible ASR")
def checkTranscriptionApiKey(api_key: str, base_url: str) -> bool:
    """`api_key`/`base_url` の組でモデル一覧が取得できるかどうかを返す。"""
    try:
        fetch_openai_models(OpenAI, api_key, base_url)
        return True
    except Exception:
        errorLogging(provider="OpenAI-compatible ASR")
        return False


@provider_errors("OpenAI-compatible ASR")
def getAvailableTranscriptionModels(
    api_key: str,
    base_url: str,
    keyword_filter: list[str] | None = None,
) -> list[str]:
    """`api_key`/`base_url` で疎通できるモデル一覧を取得する。

    `keyword_filter` が指定されていれば、モデルID (小文字化) に
    いずれかのキーワードを含むものだけに絞り込む。Groq/OpenAI公式は
    既知の Whisper 系モデル名で絞り込み、カスタムサーバーは
    (どんなモデル名を使っているか分からないため) 絞り込まずに
    全件そのまま返す想定。
    """
    res = fetch_openai_models(OpenAI, api_key, base_url)
    models = [m.id for m in res.data]
    if keyword_filter:
        models = [m for m in models if any(kw in m.lower() for kw in keyword_filter)
                  and not any(kw in m.lower() for kw in TRANSCRIPTION_MODEL_EXCLUDED_KEYWORDS)]
    models.sort()
    return models
