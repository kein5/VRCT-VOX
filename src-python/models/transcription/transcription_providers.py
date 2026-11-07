"""文字起こしエンジンをプラガブルにするためのプロバイダ抽象化。

`transcription_transcriber.py` の `transcribeAudioQueue()` が
`match self.transcription_engine: case "Google": ... case "Whisper": ...`
という形でエンジンごとの処理をハードコードしていたのを、プロバイダ
登録ベースのディスパッチに置き換える (バックエンドレビュー Phase 3
項目17 の `TranslationProvider` レジストリと同じ考え方を文字起こし側にも
展開したもの)。

VRCT の既存パイプラインは「フレーズ確定後にまとめて1回で送信する」
バッチ型のため、プロバイダのインターフェースも同期的な `transcribe()`
のみとする (常時ストリーミング前提の非同期セッション型は採用しない)。

言語候補 (`languages`/`countries`) をまたいだ「最も確信度の高い結果を
選ぶ」ループは呼び出し元 (`transcribeAudioQueue`) に共通化し、各
プロバイダは「1つの言語候補に対して1回試行する」ことだけを担当する。
"""

import math
from urllib.request import HTTPRedirectHandler, build_opener
from typing import List, Optional, Protocol, Tuple

import numpy as np
import requests
from httpx import Timeout
import speech_recognition as _speech_recognition
from speech_recognition import AudioData, Recognizer, UnknownValueError

from errors import ErrorCode
from models.transcription.transcription_deepgram import resolveDeepgramLanguageCode
from models.transcription.transcription_languages import transcription_lang
from models.transcription.transcription_openai_compatible import transcriptionResponseFormat
from utils import errorLogging
from models.diagnostics import provider_errors
from models.network_policy import api_http_client, explicit_request_auth
from models.sdk_clients import OpenAI


# speech_recognition builds the Google Web Speech URL with plain HTTP, which
# would send microphone audio unencrypted. The same endpoint serves HTTPS, so
# upgrade only that URL where the library constructs its request.
_GOOGLE_SPEECH_HTTP = "http://www.google.com/speech-api/"
_PlainRequest = _speech_recognition.Request


def _https_google_request(url, *args, **kwargs):
    if isinstance(url, str) and url.startswith(_GOOGLE_SPEECH_HTTP):
        url = "https://" + url[len("http://"):]
    return _PlainRequest(url, *args, **kwargs)


_speech_recognition.Request = _https_google_request


class _NoApiRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _speech_urlopen(request, *args, **kwargs):
    # Preserve system HTTPS proxies, but never replay audio through a redirect.
    return build_opener(_NoApiRedirect()).open(request, *args, **kwargs)


_speech_recognition.urlopen = _speech_urlopen

# setup.exe ダウンロード等の HTTP 呼び出しで使っている (10, 60) と同じ
# (connect, read) タイムアウト。実機検証の結果次第で調整する。
_HTTP_TIMEOUT = (10, 60)
_OPENAI_TIMEOUT = Timeout(connect=10, read=60, write=60, pool=10)


def _normalize_language(value: Optional[str]) -> Optional[str]:
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip().lower().replace("_", "-")
    for language, countries in transcription_lang.items():
        if value == language.lower():
            return next(iter(countries.values()))["Whisper"]
    value = {"chinese": "zh", "cantonese": "yue", "tagalog": "tl"}.get(value, value)
    base, separator, suffix = value.partition("-")
    return {"cmn": "zh", "iw": "he", "fil": "tl"}.get(base, base) + separator + suffix


def resolveDetectedLanguage(detected_language: Optional[str], languages: List[str], countries: List[str]) -> Optional[str]:
    """検出言語を選択済みの言語・国に照合する。不明なら None を保つ。"""
    code = _normalize_language(detected_language)
    if code is None:
        return None
    candidates = [(language, transcription_lang[language][country]) for language, country in zip(languages, countries)]
    # 地域・文字体系まで一致する候補を、ベース言語だけの一致より優先する。
    for language, entry in candidates:
        if detected_language.strip().lower() == language.lower() or code == _normalize_language(entry["Google"]):
            return language
    parts = code.split("-")
    if len(parts) > 1:
        for language, entry in candidates:
            candidate_parts = _normalize_language(entry["Google"]).split("-")
            if parts[0] == candidate_parts[0] and all(part in candidate_parts[1:] for part in parts[1:]):
                return language
    for language, entry in candidates:
        if code.split("-")[0] == entry["Whisper"]:
            return language
    return None


class TranscriptionApiError(Exception):
    """API 系エンジンでの文字起こし失敗を、対応する `ErrorCode` 付きで表す。"""

    def __init__(self, error_code: ErrorCode, message: str = "") -> None:
        super().__init__(message or error_code.value)
        self.error_code = error_code


class TranscriptionProvider(Protocol):
    def transcribe(
        self,
        audio_data: AudioData,
        language: str,
        country: str,
        *,
        avg_logprob: float,
        no_speech_prob: float,
        no_repeat_ngram_size: int,
        force_language: bool,
    ) -> Tuple[str, float, bool, Optional[str]]:
        """1つの言語候補に対して1回だけ試行する。

        Returns:
            (text, confidence, is_definitive, detected_language) のタプル。
            - text: 認識結果 (認識できなければ "")
            - confidence: 信頼度 (呼び出し元が複数候補から最良を選ぶ)
            - is_definitive: 自動検出など、他の候補でも同じ要求になる場合は
              True。呼び出し元は検出言語を候補に照合してループを終了する。
            - detected_language: 検出した言語名・コード。言語を明示指定した
              要求では指定コードを返す。自動検出で不明なら None。
        """
        ...


class GoogleProvider:
    """既存の `recognize_google` 呼び出しをそのまま包む。

    Google は候補言語ごとに別プロトコル呼び出しが必要で「検出された
    言語」という概念が無いため、`is_definitive` は常に False (呼び出し元は
    全候補を試行する、既存の挙動と同じ)。
    """

    def __init__(self, recognizer: Recognizer) -> None:
        self._recognizer = recognizer

    @provider_errors("Google")
    def transcribe(
        self,
        audio_data: AudioData,
        language: str,
        country: str,
        *,
        avg_logprob: float,
        no_speech_prob: float,
        no_repeat_ngram_size: int,
        force_language: bool,
    ) -> Tuple[str, float, bool, Optional[str]]:
        # 2026-09-07: クリップ前後の無音パディングやクリップ分割を
        # このプロバイダ内で行う対策を試したが、実機検証の結果「クリップの
        # 前後に無音パディングを付与する」対策はエンジンを問わず
        # AudioTranscriber 側 (transcription_transcriber.py) で一律に適用する
        # 形に一本化した。Google はこれに加えて「育っていくバッファを都度
        # 再送信する」(interim_send、AudioTranscriber側) も併用しているが、
        # このプロバイダ自体は毎回渡された audio_data を1回認識するだけで
        # 良く、パディングや再送信ロジックを知る必要はない。
        try:
            # join_all_results=True: このエンドポイントは、1クリップに
            # 複数の発話区間 (無音を挟んだ複数の文) が含まれる場合、それ
            # ぞれを別々の result ブロックとして返すことがある。既定
            # (最初のブロックだけを使う) のままだと後続の発話が黙って
            # 失われる (2026-09-07、実機で確認・custom_speech_recognition
            # フォーク側で修正)。これは上記のパディング対策とは独立した
            # 別の不具合修正なので撤回せず維持する。
            text, confidence = self._recognizer.recognize_google(
                audio_data,
                language=transcription_lang[language][country]["Google"],
                with_confidence=True,
                join_all_results=True,
            )
        except UnknownValueError:
            return "", 0.0, False, None
        return text, confidence, False, transcription_lang[language][country]["Google"]


class LocalWhisperProvider:
    """既存のローカル (faster-whisper/CTranslate2) 呼び出しをそのまま包む。"""

    def __init__(self, whisper_model) -> None:
        self._whisper_model = whisper_model

    def transcribe(
        self,
        audio_data: AudioData,
        language: str,
        country: str,
        *,
        avg_logprob: float,
        no_speech_prob: float,
        no_repeat_ngram_size: int,
        force_language: bool,
    ) -> Tuple[str, float, bool, Optional[str]]:
        raw = np.frombuffer(
            audio_data.get_raw_data(convert_rate=16000, convert_width=2), np.int16
        ).flatten().astype(np.float32) / 32768.0

        source_language = transcription_lang[language][country]["Whisper"] if force_language else None
        segments, info = self._whisper_model.transcribe(
            raw,
            beam_size=5,
            temperature=0.0,
            log_prob_threshold=avg_logprob,
            no_speech_threshold=no_speech_prob,
            language=source_language,
            word_timestamps=False,
            without_timestamps=True,
            task="transcribe",
            no_repeat_ngram_size=no_repeat_ngram_size,
        )
        text = ""
        for s in segments:
            if s.avg_logprob < avg_logprob or s.no_speech_prob > no_speech_prob:
                continue
            text += s.text

        # Whisper のセグメントは先頭に空白が付く。チャットボックスや翻訳へそのまま渡さない
        return text.strip(), info.language_probability, True, source_language or getattr(info, "language", None)


def _map_openai_exception(exc: Exception) -> ErrorCode:
    from openai import APIConnectionError, APIStatusError, APITimeoutError, AuthenticationError, RateLimitError
    if isinstance(exc, AuthenticationError):
        return ErrorCode.TRANSCRIPTION_API_AUTH_FAILED
    if isinstance(exc, RateLimitError):
        return ErrorCode.TRANSCRIPTION_API_RATE_LIMITED
    if isinstance(exc, APITimeoutError):
        return ErrorCode.TRANSCRIPTION_API_TIMEOUT
    if isinstance(exc, (APIStatusError, APIConnectionError)):
        return ErrorCode.TRANSCRIPTION_API_SERVER_ERROR
    return ErrorCode.TRANSCRIPTION_API_SERVER_ERROR


class OpenAICompatibleTranscriptionProvider:
    """OpenAI互換の音声書き起こしREST API (`/v1/audio/transcriptions`) 向け
    プロバイダ。公式 `openai` パッケージ (既存依存) の
    `client.audio.transcriptions.create(...)` を使う。

    Groq/OpenAI公式/issue #100 のカスタムローカルサーバーを、
    base_url/api_key/model の差し替えだけで1つの実装でカバーする
    (ユーザーから見えるエンジン選択肢としては、翻訳側の
    `OpenAI_API`/`Groq_API`/`OpenAI_Compatible` が別々の選択肢であるのと
    同じ構造で、`Groq_Whisper`/`OpenAI_Whisper`/`Custom_Whisper` として
    それぞれ専用のインスタンスを持つ)。

    音声フォーマットは各API先の仕様に準拠する方針のため、現時点では
    最も広くサポートされている WAV (`AudioData.get_wav_data()`) を使う。
    """

    @provider_errors(lambda self, *args, **kwargs: self.engine_name)
    def __init__(self, api_key: str, base_url: str, model: str, engine_name: str) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.engine_name = engine_name
        self._client = OpenAI(api_key=api_key, base_url=base_url, timeout=_OPENAI_TIMEOUT,
                              http_client=api_http_client(base_url, timeout=_OPENAI_TIMEOUT))

    @provider_errors(lambda self, *args, **kwargs: self.engine_name)
    def transcribe(
        self,
        audio_data: AudioData,
        language: str,
        country: str,
        *,
        avg_logprob: float,
        no_speech_prob: float,
        no_repeat_ngram_size: int,
        force_language: bool,
    ) -> Tuple[str, float, bool, Optional[str]]:
        wav_bytes = audio_data.get_wav_data(convert_rate=16000, convert_width=2)
        source_language = transcription_lang[language][country][self.engine_name] if force_language else None

        try:
            response = self._client.audio.transcriptions.create(
                file=("audio.wav", wav_bytes, "audio/wav"),
                model=self.model,
                language=source_language,
                response_format=transcriptionResponseFormat(self.model),
                temperature=0.0,
            )
        except Exception as exc:
            error_code = _map_openai_exception(exc)
            errorLogging(provider=self.engine_name)
            raise TranscriptionApiError(error_code) from None

        segments = getattr(response, "segments", None) or []
        accepted_logprobs: List[float] = []
        text = ""
        if segments:
            for s in segments:
                if s.avg_logprob < avg_logprob or s.no_speech_prob > no_speech_prob:
                    continue
                text += s.text
                accepted_logprobs.append(s.avg_logprob)
        else:
            # verbose_json 非対応のサーバー (カスタムサーバー等) は
            # segments を返さないことがある。その場合はセグメント単位の
            # フィルタリングができないため、テキストをそのまま採用する。
            text = getattr(response, "text", "") or ""

        text = text.strip()
        if not text:
            return "", 0.0, False, None

        # avg_logprob (対数確率、概ね負の値) を 0〜1 の疑似的な信頼度に変換する。
        # ローカル Whisper の info.language_probability に相当するものが
        # verbose_json には無いため、代替の指標として使う。
        confidence = math.exp(sum(accepted_logprobs) / len(accepted_logprobs)) if accepted_logprobs else 0.5

        # 自動検出の要求は候補を変えても同じ。検出言語が無い場合も
        # 1回で終え、呼び出し元で不明な言語を候補の先頭に置き換えない。
        detected_language = source_language or getattr(response, "language", None)
        return text, confidence, True, detected_language


_DEEPGRAM_LISTEN_URL = "https://api.deepgram.com/v1/listen"


def _map_deepgram_status(status_code: int) -> ErrorCode:
    if status_code in (401, 403):
        return ErrorCode.TRANSCRIPTION_API_AUTH_FAILED
    if status_code == 429:
        return ErrorCode.TRANSCRIPTION_API_RATE_LIMITED
    return ErrorCode.TRANSCRIPTION_API_SERVER_ERROR


class DeepgramProvider:
    """Deepgram の録音済み(バッチ) REST API (`/v1/listen`) 向けプロバイダ。

    OpenAI互換ではないため `openai` パッケージは使わず、既存依存の
    `requests` で直接叩く。

    言語コードについて: 候補言語が1つに確定している場合
    (`force_language=True`)、`resolveDeepgramLanguageCode()` で
    このモデルが実際に対応言語として申告しているコード (Google列との
    完全一致、または Whisper列のベースコード一致) を解決できれば、
    それを `language=` として明示的に渡す。解決できない場合
    (対応コードが不明、または候補言語が複数で1つに絞れない場合) は
    `detect_language=true` (自動検出) にフォールバックする。
    いずれの経路でも1回のAPI呼び出しで完結するため
    (Deepgram自身が1呼び出しで多言語を判定できる)、`is_definitive` は True を
    返し、呼び出し元のループを1回で打ち切らせる。

    信頼度についても、avg_logprob/no_speech_prob に相当するセグメント
    単位の指標をDeepgramは返さないため、トップレベルの `confidence`
    (0〜1) をそのまま使う (セグメント単位のフィルタリングは行わない)。
    """

    def __init__(self, api_key: str, model: str, model_languages: Optional[List[str]] = None) -> None:
        self.api_key = api_key
        self.model = model
        self.model_languages = model_languages or []

    @provider_errors("Deepgram")
    def transcribe(
        self,
        audio_data: AudioData,
        language: str,
        country: str,
        *,
        avg_logprob: float,
        no_speech_prob: float,
        no_repeat_ngram_size: int,
        force_language: bool,
    ) -> Tuple[str, float, bool, Optional[str]]:
        wav_bytes = audio_data.get_wav_data(convert_rate=16000, convert_width=2)

        params = {"model": self.model}
        resolved_code = resolveDeepgramLanguageCode(language, country, self.model_languages) if force_language else None
        if resolved_code:
            params["language"] = resolved_code
        else:
            params["detect_language"] = "true"

        try:
            response = requests.post(
                _DEEPGRAM_LISTEN_URL,
                headers={
                    "Authorization": f"Token {self.api_key}",
                    "Content-Type": "audio/wav",
                },
                params=params,
                data=wav_bytes,
                timeout=_HTTP_TIMEOUT,
                allow_redirects=False,
                auth=explicit_request_auth,
            )
        except requests.exceptions.Timeout:
            errorLogging(provider="Deepgram")
            raise TranscriptionApiError(ErrorCode.TRANSCRIPTION_API_TIMEOUT) from None
        except requests.exceptions.RequestException:
            errorLogging(provider="Deepgram")
            raise TranscriptionApiError(ErrorCode.TRANSCRIPTION_API_SERVER_ERROR) from None

        if response.status_code != 200:
            errorLogging(provider="Deepgram", status=response.status_code)
            raise TranscriptionApiError(_map_deepgram_status(response.status_code))

        try:
            payload = response.json()
            channel = payload["results"]["channels"][0]
            alternative = channel["alternatives"][0]
            text = alternative["transcript"]
            confidence = alternative["confidence"]
            if (not isinstance(text, str) or type(confidence) not in (int, float)
                    or not math.isfinite(confidence) or not 0 <= confidence <= 1):
                raise ValueError("invalid transcription result")
        except (KeyError, IndexError, TypeError, ValueError, OverflowError):
            errorLogging(provider="Deepgram")
            raise TranscriptionApiError(ErrorCode.TRANSCRIPTION_API_SERVER_ERROR) from None

        if not text:
            return "", 0.0, False, None

        # 明示コード・自動検出のいずれでも1回の呼び出しで完結するため、
        # この1回の結果が最終結果。呼び出し元 (transcribeAudioQueue) には
        # 他の候補言語を試させない。
        return text, float(confidence), True, resolved_code or channel.get("detected_language")
