# Linux build pipeline design

ユーザー依頼: Linux用ビルドパイプラインを作る。既存の閉ループ実装方針を継続。
基準: [Linux配布案](../../voice-stack/linux-distribution-proposal.md)、配布5条件、元実装仕様。

## Deliverable

ローカルとGitHub Actionsで同じ入口から、Linux x86_64のTauri + frozen Python sidecar +
4 native helpers + speech.cpp 0.9.0を生成する。主成果物はsymlinkを保持するtar.gz、SHA-256、
内容/依存のinventoryと通知。checkout/venvのない別ディレクトリで起動できる候補を実証する。
公開/タグ/push/AUR登録/上流PRを行わない。Windows設定・開発sidecarを上書きしない。

## Choices

- PyInstaller onedirを採用。既存Windows freeze構造を使いつつLinux専用specを作る。
  venv同梱はPython絶対パス/外部checkout問題、Nuitka等への変更は保守・検証範囲拡大のため見送る。
- Linux archiveはtar.gz。PyInstaller公式のsymlink保持要件による。AppImage/Flatpakは後続。
- CIはUbuntu 24.04 x86_64、Python 3.11、uv、npm ci、locked Cargoを用いる。
  ローカルCachyOS buildとCI buildのglibc下限を同一視しない。ELF依存を記録する。
- Python依存はLinux向けcompile済みlock。Git依存は既存commitを維持。モデルを取得しない。
- speech.cppは既承認の固定CPU/Vulkan archiveから選択。hashと通知を既存stage toolで検査。
- Tauri build入力をbuild領域へ分離。元のsrc-tauri/binと開発native binaryを上書きしない。

## Runtime layout and paths

`VRCT-TTS/vrct-tts`, `vrct-tts-sidecar`, `_internal/`（Python/runtime/資源）、
`_internal/build/`（native helpers/speechcpp）、`_internal/integrations/`（外部VC接続ソース/通知）。
本体は不変。Linux frozenだけconfig/log/data/cacheをXDGのvrct-tts専用領域へ置く。
既存`VRCT_CONFIG_DIR` overrideを保持し、開発/Windowsの既定パスは変更しない。
`PATH_LOCAL`は既存資源の基準として保持、重み等の可変用途だけ`PATH_DATA`へ分離する。
native helperの場所は`runtime_paths.resource_root()`から解決。外部プロセスへPyInstallerが
変更したLD_LIBRARY_PATHを漏らさず、app自身の環境は変えない。

## Gates

OCR全重み/Mia2026/追加TTS-ASR-VC重みを収集しない。元LICENSE/モデル通知とspeech.cpp通知、
Python dependency metadata/license files、同梱integration sourceの通知を残す。
既存faster-whisper依存のVAD ONNXは音声機能の既存資源として区別しinventoryへ記録する。
ライセンスmetadataは再配布許可の判定ではない。最終ライセンス/Trail of Bits監査は公開前に残す。

リンクはbundle内部の通常ファイルへ解決するものだけ許可。壊れたリンク、外部参照、循環、
archiveの絶対/親参照パス、特殊file、重複entryを拒否し、検査できないものをPASSにしない。
buildや検査失敗時は候補artifact uploadを行わない。新しいモデル、マイク録音、VRChat送信なし。

## Acceptance

純粋path/collector/archive契約をRED→GREEN。標準Pythonと音声関連回帰を実行。
実PyInstaller/Tauri build、移設後のstdio初期化/停止、読み取り専用bundleでの設定保存/再起動、
実Tauri描画と専用PipeWireのミュートを検証。可能なら承認済みモデルでowned speech smoke。
GitHub-hosted runnerでのworkflow実行はローカル成功で代替せず、未実行なら明記する。

原典: [PyInstaller pitfalls](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html)、
[Tauri Linux prerequisites](https://v2.tauri.app/start/prerequisites/#linux)、
既存imozuru配布調査。問題発生時は原典/関連実装を保存して追跡する。
