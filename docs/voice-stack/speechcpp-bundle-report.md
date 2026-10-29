# speech.cpp固定配布部品 — 2026-10-29

**Linux CPU/Vulkanの配布部品を作成・検証済み。GUIへの組み込みとアプリ全体の配布は未完了。**
[30分複合試験](combined-voice-resume-2026-10-29.md)の通過後に着手。コードは`bcd5c623`。
[設計](../superpowers/specs/2026-10-29-speechcpp-bundle-artifact-design.md)・
[計画](../superpowers/plans/2026-10-29-speechcpp-bundle-artifact.md)に従う。

## 作成方法と境界

[同梱ツール](../../tools/speechcpp_bundle.py)は、ローカルZIPまたは明示的な`--download`から
speech.cpp **0.9.0** の固定公式releaseを検証し、実行ファイル、7個の通知文書、`bundle.json`だけを作る。
取得サイズ・SHA256・source commit・通知原典は[固定台帳](speechcpp-bundle-artifacts.json)。
モデル・参照音声・Mia2026・VC runtime・libspeech共有ライブラリは含まない。
ダウンロードは開発/ビルド時だけで、アプリ起動から呼ばれない。

```sh
UV_CACHE_DIR=/tmp/vrct-uv-cache uv run --no-project --python /usr/bin/python3 python \
  tools/speechcpp_bundle.py --variant linux-x64-vulkan \
  --archive /path/to/speech-0.9.0-linux-x64-vulkan.zip --output /path/to/new/speechcpp
```

オンライン取得する場合のみ`--archive PATH`を`--download`に置き換える。
既存の出力先は上書きしない。これはモデル取得のコマンドではない。

## 自動試験と実物検証

新規33ケースのREDを確認後、配布・取得関連は65 PASS。
ローカルレビューで2ケースを追加し、修正前2 FAIL→修正後**67 PASS**（0.39秒、既存openvr警告1）。
検証後の元ZIPの差し替えに備え、実際に展開する私有コピーをhash検証するよう修正。
FIFO等の`bundle.json`も読み始める前に拒否する。
改ざん・サイズ超過・切断・重複/リンクされた実行ファイル・通知不足・既存出力保護、
Python最適化時の検証維持と、余分な私有モデルを追加した部品の拒否を確認した。

原典はPython公式の[ZipFile](https://docs.python.org/3.11/library/zipfile.html#zipfile.ZipFile)と
[TemporaryFile](https://docs.python.org/3.11/library/tempfile.html#tempfile.TemporaryFile)、
実行中のCPython 3.11.17の実装。imozuru追跡は`tmp/voice-resume/research/speech-bundle/`。
これは局所レビューであり、後日依頼されたTrail of Bits監査の代替ではない。

| 実物 | CPU | Vulkan |
|---|---:|---:|
| 公式ZIPの検証サイズ | 5,471,367 bytes | 31,684,675 bytes |
| 展開したspeech | 8,536,032 bytes | 50,727,760 bytes |
| 完成部品（9ファイル合計） | 8,584,038 bytes | 50,775,777 bytes |
| 移設後`--version` | exit 0、speech.cpp 0.9.0 / C API 3.4 | 同左 |
| ELFが要求する最大GLIBC symbol | 2.34 | 2.34 |
| 新しいHOME/作業ディレクトリの生成ファイル | 0 | 0 |

CPU実行ファイルSHA256: `394fd7c0636143fa96fc961af55f1bcdcf71fa557e4c210e231eb253a97353d8`。
Vulkan実行ファイルSHA256: `800e9bae0057a7ce2b63dde01a71bf83653ffbd70eb83f8bea3e8fd944f678e7`。

最終コードで公式ZIPを再検証し、別ディレクトリへコピーしてから新しいHOME・空のcwd・
空の`LD_LIBRARY_PATH`で実行。両部品で禁止OCR/Mia2026検査もexit 0。
CPUはlibm/libc/動的ローダー、Vulkanは追加でlibvulkan.so.1を要求する。
libspeechや開発checkoutにあるライブラリへの動的依存はない。
ただしVulkan版に上流CIの絶対RUNPATH
`/home/runner/work/_temp/1.4.357.0/x86_64/lib/VulkanLoader/lib`が残る。
このPCではそのディレクトリなしで起動成功。バイナリを書き換えず配布記録に保持する。
他ディストリビューション全体への互換性をこの1台だけで保証しない。

実物: `tmp/voice-resume/speech-bundle/verified/{linux-x64-cpu,linux-x64-vulkan}/`。
元ZIP・移設後部品・`relocation-final.json`も同ディレクトリ以下、Git管理外。
試験環境は前記複合試験と同じLinux PC。モデルを起動せず、推論性能は再測定していない。

## 残るP5工程

- GUIからの同梱サーバー起動・状態・停止と、外部サーバー設定の互換性。
- 親アプリ終了/強制終了に追随した所有プロセス回収、ロード中停止、再起動時OFF。
- Linuxアプリ全体のパッケージ、可変設定保存先、fork名/識別子/更新先、依存の最終通知。
- 同梱版を使ったGUIのTTS/ASR再受入れとWindows PCでの対応。
- アプリ全体のTrail of Bits Skills監査と、未検証の物理/聴感/VRChat/HMDゲート。

公開・push・上流連絡・PRは行っていない。
