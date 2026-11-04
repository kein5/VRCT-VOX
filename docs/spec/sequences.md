# シーケンス

代表的な場面のやり取り。すべての場面ではなく、起動、よく使う操作、外部とのやり取り、エラーの経路が分かるものを選んでいる。メッセージの形は[IPCプロトコル](ipc-protocol.md)、エンドポイントは[一覧](reference/ipc-endpoints.md)にある。

## 起動

```mermaid
sequenceDiagram
  autonumber
  participant UI as UI（main）
  participant S as サイドカー
  participant Net as ネットワーク
  UI->>S: spawn（bin/vrct-vox-sidecar）
  Note over S: 受信とワーカー3本が先に動く。<br/>status False の要求は423で待たせる
  S->>Net: GET https://www.google.com（3秒）
  S-->>UI: /run/connected_network
  S-->>UI: /run/initialization_progress = 1
  opt オンラインで AUTO_DOWNLOAD_MODELS がオン
    S->>Net: 内蔵モデルの取得
  end
  S-->>UI: /run/enable_ai_models（真偽）
  S->>Net: 各エンジンのキーとモデル一覧の確認
  Note over S: 確認できないキーも保存したままにする
  S-->>UI: /run/initialization_progress = 2
  S-->>UI: /run/selected_translation_engines、/run/translation_engines
  S-->>UI: /run/initialization_progress = 3、4
  S-->>UI: /run/enable_osc_query（OSCQueryが使えないとき）
  S-->>UI: /run/initialization_complete {"/get/data/…": 値}
  Note over S: 全エンドポイントのロックを外す
  UI->>UI: 受信先へ配り、起動画面を閉じる
  UI->>S: 音声・音声サーバー・モデル取得の状態を取得
  loop 20秒ごと
    UI->>S: /run/feed_watchdog
  end
```

- サイドカーのstderrに警告以外の行が出たら、UIは消えない通知を出す。
- `/run/enable_ai_models`が偽なら、UIは内蔵モデルがないことを知らせる。
- spawn失敗と初期化項目の失敗の分岐、再マウントと手動再試行の扱いは[起動と初期化](ipc-protocol.md#起動と初期化)を参照する。

## 設定の変更

```mermaid
sequenceDiagram
  autonumber
  participant P as 設定画面
  participant UI as UI（ロジック）
  participant S as サイドカー
  participant F as config.json
  P->>UI: 値を変える（スイッチ、または保存バーの「保存」）
  UI->>UI: 値を pending にする
  UI->>S: /set/data/x（data = base64(JSON)）
  S->>S: エンドポイントのロック、検証
  alt 検証に通る
    S->>S: 値を保存（2秒後にまとめて書く）
    S-->>UI: 200 /set/data/x = 保存後の値
    UI->>P: 値を反映、「保存しました」
    S->>F: 一時ファイルに書いて置き換える
  else 検証に通らない
    S-->>UI: 400 {error_code: VALIDATION_…, data: 元の値}
    UI->>P: 元の値に戻し、理由を通知
  end
```

言語と翻訳エンジンの変更では、応答の前に次の通知が届く。

```mermaid
sequenceDiagram
  participant UI
  participant S as サイドカー
  UI->>S: /set/data/selected_target_languages
  opt エンジンが対応しない言語
    S-->>UI: /run/selected_your_languages、/run/selected_target_languages
    S-->>UI: 400 /run/translation_language_unsupported
  end
  S-->>UI: /run/selected_translation_engines
  S-->>UI: /run/translation_engines
  S-->>UI: 200 /set/data/selected_target_languages
  alt 30秒以内に応答がない、または400・404・423・500
    UI->>S: 言語に関する値をすべて読み直す
  end
```

## チャットの送信

```mermaid
sequenceDiagram
  autonumber
  participant UI as UI
  participant S as サイドカー
  participant T as 翻訳エンジン
  participant V as VRChat（OSC）
  participant W as WebSocket・OBS
  participant Q as 読み上げの待ち行列
  UI->>UI: ログに「送信中」の行を出す
  UI->>S: /run/send_message_box {id, message}
  Note over S: 受信時に音声の世代番号を付ける。<br/>処理の受付時に内容設定とチャットボックスの番号を固定する
  opt TTS が原文を読む設定
    S->>Q: 原文を積む
  end
  opt 翻訳がオン
    S->>T: 相手の言語ごとに翻訳（並行）
    alt エンジンが失敗
      S->>S: CTranslate2 で訳し直す
      S-->>UI: /run/selected_translation_engines、/run/translation_engines
      S-->>UI: 400 /run/error_translation_engine
    end
  end
  opt 現在の送信設定がオンで、より新しい番号をOSCへ送っていない
    S->>V: /chatbox/input [書式を当てた文, true, 通知音]
  end
  S->>W: {type: "CHAT", …}
  opt TTS が訳を読む設定で、選んだ枠に実際の訳文がある
    S->>Q: 訳を積む（世代が古ければ捨てる）
  end
  opt 出力先の一部で例外
    S-->>UI: 400 /run/message_output_error（出力先別の警告）
  end
  S-->>UI: 200 /run/send_message_box {id, original, translations, output_failures?}
  UI->>UI: 行を訳つきに置き換える
```

設定の固定、古いOSC送信の省略、出力先の例外の扱いは[メッセージの受付と出力](cross-cutting.md#メッセージの受付と出力)に従う。各出力の例外はその時点で通知し、後続の処理を続ける。

送信に失敗した場合の行の状態は、[会話メッセージのデータ形式](data-and-persistence.md)を参照。

## マイクの文字起こし

```mermaid
sequenceDiagram
  autonumber
  participant UI
  participant S as サイドカー
  participant Mic as マイク
  participant E as 音声認識エンジン
  participant V as VRChat（OSC）
  UI->>S: /set/enable/transcription_send
  S-->>UI: 200 /set/enable/transcription_send = 開始できたか
  opt 選んだマイクがない
    S-->>UI: 400 /run/error_device {error_code: DEVICE_NO_MIC}
  end
  loop 発話ごと
    Mic->>S: 感度を超えた音
    Note over S: 無音が続く・15秒を超える・待ち時間を過ぎると区切る
    S->>E: 自分の言語ごとに認識し、確信度の高い結果を採る
    alt 認識に失敗
      S-->>UI: /set/disable/transcription_send = false
      S-->>UI: /run/transcription_recognition_error
    else ワードフィルターに一致
      S-->>UI: /run/word_filter
    else 認識できた
      S->>S: 翻訳（オンのとき）
      S->>V: /chatbox/input（送信がオンのとき）
      S-->>UI: /run/transcription_send_mic_message
    end
  end
```

- スピーカー側（聞き取り）は同じ流れで、相手の言語で認識し、自分の言語へ訳す。VRChatへ送るのは「受信したメッセージをVRChatに送信する」がオンのときだけで、通知は`/run/transcription_receive_speaker_message`になる。
- Linuxでは、マイク入力のスイッチがリアルタイム音声認識を始め、結果は`/run/realtime_caption`で届く。

## 読み上げと停止

```mermaid
sequenceDiagram
  autonumber
  participant UI
  participant R as 受信スレッド
  participant S as サイドカー（ワーカー）
  participant Srv as 音声サーバー
  participant Out as 出力デバイス
  UI->>S: /run/enable_tts {generation}
  S->>S: 読み上げの元・言語・出力先を確かめる
  opt 同梱サーバーを使う
    S->>Srv: 起動して準備を待つ
  end
  alt 条件がそろう
    S-->>UI: 200 音声の状態
  else そろわない
    S-->>UI: 409 {error_code: tts_…}
  end
  loop 待ち行列
    S->>Srv: POST /v1/audio/speech
    Srv-->>S: audio/pcm
    S->>Out: 再生
  end
  UI->>R: /run/stop_voice
  Note over R: キューを通らず、すぐ処理する
  R->>S: 世代番号を進め、待ち行列を空にし、再生を止める
  R-->>UI: 200
  UI->>R: /run/mute_voice
  R-->>UI: 200 {pending: true}
  Note over S: 管理対象の経路では仮想マイクの出力を止める（読み上げとRVCの両方）
```

## APIキーの登録

```mermaid
sequenceDiagram
  autonumber
  participant P as 設定画面
  participant S as サイドカー
  participant C as クラウドのサービス
  P->>S: /set/data/groq_whisper_auth_key（保存バーの「保存」）
  S->>C: モデル一覧の取得（Deepgram は /v1/auth/token で確認）
  alt 認証とモデルの確認がすべて成功
    S->>S: 共有ロック内で対象のキーと準備済みの状態を反映
    S-->>P: /run/selectable_groq_whisper_model_list
    S-->>P: /run/selected_groq_whisper_model
    S-->>P: 200 キー
    P->>S: /get/data/selectable_transcription_engines、/get/data/selected_transcription_engine
    P->>P: エンジンを選べるようにする
  else 確かめられない（拒否、形式の誤り、通信失敗、モデルなし、初期化失敗）
    S->>S: 保存してあるキーと状態はそのまま
    S-->>P: 400 {error_code: TRANSCRIPTION_API_AUTH_FAILED, data: 保存してあるキー}
    P->>P: 欄を保存してあるキーに戻し、理由を通知
  end
```

翻訳のキー（`/set/data/groq_auth_key`など）も同じ流れで、エラーコードは`AUTH_…`になる。準備と反映、同時変更、OpenAI互換URLの失敗時の扱いは[APIキーの変更](cross-cutting.md#apiキーの変更)に従う。

従来の文字起こしと音量メーターの開始・停止、Auto選択、機器の切り替えは、[音声デバイスの選択と識別](data-and-persistence.md#音声デバイスの選択と識別)に従う。機器の切り替えでは、開けた収録先を通知してから変更前後の名前を知らせる。録音エラーは文字起こしの処理を待たずに検出し、メーターだけが動いている場合も終了を通知する。
