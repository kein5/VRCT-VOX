# チャット入力の小窓

本体を前面へ戻さず、設定したキーで入力専用のウィンドウを開く。初期状態ではキーを
割り当てない。ホットキー設定の「入力の小窓を開く」ボタンでも開ける。
小窓は開くたびに最前面へ指定してから表示・最小化解除・フォーカス移動する。
表示中は他の通常ウィンドウより手前に保つ。本体の最小化状態は変更しない。
ホットキーはキーを離した時点で小窓を開く。
Escまたはウィンドウの閉じる操作で非表示にし、終了するまでは下書きを保持する。
Enterで送信、Shift+Enterで改行する。本体の「Enter送信を無効にする」と自動クリア設定を引き継ぐ。
IME変換中のEnterとキーリピートは送信しない。

## 本体への受け渡し

小窓のエントリーは `src-ui/quick-chat.html`。本体のAppやStartPythonControllerを読み込まない。
ウィンドウlabelは `quick_chat`、サイズは480×160（最小320×120）。同じウィンドウを再利用する。

1. 小窓はUUIDと文字列をnative commandへ渡す。Rustは実際の呼出元label、ID形式、空白だけの
   入力を検証し、一度に一件の要求を保持する。
2. 本体宛てのイベントには本文を載せず、要求があることだけを通知する。
   本体はnative commandから未処理の要求を一度だけ取り出す。任意のイベント本文から送信しない。
3. 本体の `useMessage.sendMessage` が既存sidecarの `/run/send_message_box` へ渡す。
   履歴、翻訳、OSC、TTSは本体と同じ経路になる。小窓はsidecarを起動しない。
4. 同じIDの再通知では再送しない。直近64件の受け渡し結果を保持する。
   送信確認はsidecarのstdin書込み完了であり、翻訳や音声再生の完了通知ではない。

送信待ち中は入力と送信ボタンをロックする。5秒で確認が届かなければ理由を表示し、
確認が来るまで次の送信を許可しない。失敗や未確認で下書きを消さない。空白だけの本文は
共通送信hookでも拒否する。本体にはチャット本文の最大長が定義されていないため、
小窓だけの文字数制限や切り詰めは追加しない。OSCの表示処理も既存のまま。

`quick-chat` capabilityは小窓だけを対象にし、イベント購読・解除だけを許可する。
新規native commandはそれぞれ `main` / `quick_chat` を検証する。シェルやファイル操作の
権限を小窓へ追加しない。設定画面が開いている間や本体が準備中は受け渡しを拒否する。

## ショートカットとWayland

既存のTauri global-shortcut pluginを再利用する。固定依存 `global-hotkey 0.6.4` の
ローカルソースはLinuxをX11のみとしている。Windowsの登録経路も既存のまま。
過去の4項目だけを持つHOTKEYS設定は、値を保持したまま `open_quick_chat: null` を補う。

[GlobalShortcuts portalの原典](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.GlobalShortcuts.html)
では、CreateSession、BindShortcuts、Activatedによる通知を定義している。
Activatedの `activation_token` は対象ウィンドウをアクティブにするために使う。
登録だけでフォーカス移動まで保証できるものではない。

この変更でportalを実装したとは扱わない。ネイティブWaylandを検出した場合は登録を試みず、
未対応の理由とボタンでの開き方を表示する。XWaylandでは既存登録を試みるが、他のWayland
アプリを操作しているときのキーとフォーカスはデスクトップの制限を受け得る旨を表示する。
OS登録エラーとウィンドウ表示・フォーカスAPIの失敗も通知する。
Windowsでの実機動作、物理IME、VRChat入力中の挙動は未検証。

Yキーの既定割当て、任意キーをVRChatへ渡さない仕組み、VR空間の入力パネルは含めない。

## ゲームより手前に表示する処理

フォーカス移動だけでは、最前面指定のゲームに隠れるため、小窓にも最前面指定を行う。
LinuxではGTKのメインスレッド上で表示・最小化解除・フォーカス要求を順に実行する。
X11/XWaylandのグローバルキーはGTKの入力イベントではないため、通常の
`present_with_time(GDK_CURRENT_TIME)` は古いGTK入力時刻を使い、KWinにフォーカスを
拒否される場合がある。今回の要求時にXサーバーの時刻を取得して渡す。
`get_server_time` の前提であるproperty-changeイベントマスクを追加してから取得する。
GTKとgdkx11は元からlockfileにある同じ版をLinuxの直接依存として指定し、追加取得はしない。
WaylandではX11の関数を呼ばず、GTKの通常の表示要求を使う。

また、X11のキー押下処理中にフォーカスを移すと、global-hotkeyがキー解放を受け取れず
押下中の状態が残り、次の押下を無視するケースを確認した。Quick Chatの起動は
`Released` イベントで行い、キーの解放後にフォーカスを移す。他のホットキーは従来の
`Pressed` のまま。診断は専用のライブラリコピーで行い、固定依存の本体は変更しない。

参照: [GTKの表示要求](https://docs.gtk.org/gtk3/method.Window.present_with_time.html)、
[Xサーバー時刻とイベントマスクの条件](https://docs.gtk.org/gdk3-x11/func.x11_get_server_time.html)。

回帰テストは専用の全画面・最前面GTKウィンドウを同じモニターに置き、両窓が実際に
重なる座標であることも検査する。初回・Esc後・最小化後・表示中の再呼び出しについて、
重なり順、入力フォーカス、本体の最小化維持、下書き保持を調べる。

2026-10-29の最終確認ではネイティブ試験3件が成功し、前面表示の4パターンは追加2回も成功した。
既存の翻訳・OSC・TTS送信は各1回、sidecarは1プロセスのまま。ブラウザ・設定回帰4件と
Rust試験2件も成功した。実VRChat・HMD・Windowsはこの試験に含めていない。
修正版は `build/quick-chat-foreground-artifacts/` にローカル生成し、旧候補は維持した。
AppImageのSHA-256は `11c9d3e8cd34836223e9b48fb42c78754fee59aa5f8b26aa55d9f404e71a0e17`。
