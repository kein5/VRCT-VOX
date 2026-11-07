# 用語集

仕様書とコードで使う言葉。画面の名前は`locales/ja.yml`に合わせる。

| 用語 | 意味 | コードでの名前 |
|---|---|---|
| サイドカー | UIが起動するPythonのプロセス。翻訳、音声認識、OSCなどの処理を受け持つ | `bin/vrct-vox-sidecar`、`src-python/` |
| エンドポイント | IPCの要求と通知の宛先。`/get/data/…`のような文字列 | `mapping`、`run_mapping` |
| 要求 | UIからサイドカーへのメッセージ。必ず応答が返る | `asyncStdoutToPython` |
| 通知 | サイドカーが自分から送るメッセージ。UIは返事をしない | `controller.run`、`/run/…` |
| 初期化の完了 | 起動時にサイドカーが全設定をまとめて送ること | `/run/initialization_complete` |
| 保存バー | 設定画面の上部にある、未保存の変更の件数と「保存」「破棄」のボタン | `SaveBar`、`setSaveBarEntry` |
| タブ | 言語と翻訳エンジンの組を3つまで切り替える仕組み（1〜3） | `selected_tab_no` |
| あなたの言語、相手の言語 | 自分が話す言語と、訳す先の言語（最大3つ） | `selected_your_languages`、`selected_target_languages` |
| 内蔵モデル | アプリの中で動く翻訳（CTranslate2）と文字起こし（Whisper）のモデル | `weights/` |
| 同梱サーバー | アプリが起動して管理するspeech.cppのサーバー（TTSとASR） | `speech_server` |
| 外部サーバー | 利用者が別に起動したspeech.cppのサーバー | `external` |
| 音声経路 | 読み上げとRVCの音声をVRChatへ届ける道筋 | `voice_route` |
| 管理対象の経路 | 画面では「管理対象の仮想マイク（Linux）」。アプリが作るLinuxの仮想マイクを使う経路。ミュートは読み上げとRVCの両方に効く | `managed`、`vrct.managed.source` |
| 既存の外部ケーブル | 利用者が用意した仮想ケーブルを使う経路 | `external` |
| 入力の転送（RVC） | マイクの声をRVCで変換して仮想マイクへ流すこと | `direct_voice` |
| 世代番号 | 停止のたびに進む番号。古い世代の読み上げを鳴らさないために使う | `generation`、`epoch`、`_voice_generation` |
| チャット読み取り | VRChatのチャットボックスを画面から読み取るOCRの機能 | `ocr_capture` |
| リアルタイム音声認識 | 話している途中から字幕を出す音声認識。Linuxと、同梱サーバーを選んだWindowsのメインスイッチが使う | `realtime_asr`、`/run/realtime_caption` |
| 字幕オーバーレイ | VRの視界に会話を出す表示（一行・複数行） | `overlay_small_log`、`overlay_large_log` |
| VR UI | VRの中で操作する手首のランチャーとウィンドウ | `vr_panel` |
| チャット入力の小窓 | ホットキーで開く入力専用のウィンドウ | `quick_chat` |
| OSCQuery | VRChatのOSCの受け口を探す仕組み。VRCマイクミュート同期に使う | `tinyoscquery` |
| VRCマイクミュート同期 | VRChatでミュートしている間、マイクの認識結果を送らない機能 | `vrc_mic_mute_sync` |
| ワードフィルター | 指定した語を含む認識結果を送らない機能 | `mic_word_filter` |
