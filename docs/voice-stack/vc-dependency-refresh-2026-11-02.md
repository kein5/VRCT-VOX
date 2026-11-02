# RVC・Seed-VC実行環境の依存更新と再検証

2026-11-02。Dependabotが`integrations/rvc`と`integrations/seed_vc`の依存ファイルに出していた警告（133件。重大5、高45）のうち、Pillow・Transformers・filelock・setuptoolsの修正版へ上げ、旧版と同じ試験で比べた。
どちらも任意の外部実行環境で、アプリの配布物には含まない。torchの警告（中・低）は対象外で、末尾に残す。

## 変更した版

| パッケージ | Seed-VC | RVC |
|---|---|---|
| Pillow | 12.3.0 → 13.0.0 | 含まない |
| Transformers | 4.46.3 → 5.22.1 | 4.49.0 → 5.22.1 |
| huggingface-hub | 0.28.1 → 2.4.0（Transformers 5の要求） | 2.4.0（新規） |
| tokenizers | 0.20.3 → 0.23.3 | 0.23.3 |
| filelock | 3.32.3 → 4.2.4 | 4.2.4 → 4.2.6 |
| setuptools | 84.2.1（変更なし） | 78.1.0 → 84.2.1 |

torch・torchaudio・torchvisionと、エンジンのソース（RVC `81eed5e8`、Seed-VC `58d0ca37`＋`offline-loader.patch`）は変えていない。
PyTorchの公式indexにはsetuptoolsが78.1.0までしかないため、RVCは2段目の`requirements.lock`（PyPI）で84.2.1に置き換える。インストール手順は変えていない。

Seed-VCの`requirements.lock`は、検証済みの`requirements.freeze.txt`から上の版だけを動かした入力（CUDA版の3つは公式URLとハッシュで固定）を`uv pip compile --generate-hashes`で解決した。
RVCの`requirements.lock`は`requirements.in`から解決した。どちらも、lockから新しく作った環境の`uv pip freeze`が、試験した環境と一致することを確かめた。

## 環境

| 項目 | 値 |
|---|---|
| GPU / driver | RTX 4080 SUPER / 615.78.08 |
| Seed-VC | Python 3.11.17、torch 2.10.0+cu128 |
| RVC | Python 3.12.14、torch 2.7.1+cu118 |
| モデル | RVC基礎モデル（[固定manifest](rvc-base-artifacts.proposal.json)）、Seed-VCの5モデル（[固定manifest](seed-vc-poc-artifacts.json)）。どちらもユーザーの承認を得て取得し、サイズとハッシュを照合した |
| RVCの話者モデル | ユーザー提供のMia2026（`.pth`と`.index`）。[前回の検証](rvc-mia-validation-2026-10-29.md)と同じ条件で、読み込むだけにした |
| 音声 | ユーザーが使用を許可したローカルのWAV（48 kHz、モノラル、16 bit、14.3秒）を、Seed-VCの参照音声と各変換の入力に使った |

最初の試験は、別のGPUアプリ（ComfyUI）が処理中で、Seed-VCの変換が1回GPUメモリ不足で失敗した。以下の比較は、そのアプリが待機中の状態でやり直した結果である。

## 結果

| 試験 | 旧版 | 新版 |
|---|---|---|
| Seed-VC `smoke`（5モデルの読み込みとVAD） | 成功 | 成功。報告は所要時間以外すべて一致（GPUメモリ最大964,513,792 bytes、VAD 72チャンク・10区間） |
| Seed-VC `convert`（`--profile low`、各2回） | 成功 | 成功。出力の相関は4回とも1.000。旧版1回目と新版1回目のブロック判定は全260ブロックで一致 |
| RVC モデルなし試験（`test_rvc_worker.py`、`test_rvc_runtime.py`） | 22件成功 | 22件成功 |
| RVC HuBERTの特徴量（CPU、float32） | — | 旧版と完全に一致（最大差0.0）。欠け・余りの重みなし。float16指定も有効 |
| RVC 実モデル試験（`test_native_rvc_worker.py`、私有PipeWire、4ケース） | 4件成功 | 4件成功 |

RVC実モデル試験の、入力ブロックの終わりから出力の書き込みまでの時間（各ケース14回）は、旧版が中央値53.4〜61.1 ms・95%点61.4〜66.4 ms、新版が中央値53.5〜61.5 ms・95%点59.2〜63.8 msだった。起動から変換開始までは、どちらも5.3〜7.5秒。

Transformers 5は、XLS-Rの読み込みで事前学習用の7つの重み（quantizerなど）を「UNEXPECTED」と一覧表示する。旧版でも同じ7つを`unused`と数えており、読み込む内容は変わっていない。

Seed-VCのVADによるブロック判定は、同じ版どうしでも実行ごとに7〜26ブロック変わった。処理のタイミングに依存するもので、版による違いではない。

## 確認していないこと

聴感での品質、物理マイクとVRChat、長時間の連続動作、Windows。

## 残る警告

RVCのtorch 2.7.1+cu118に、中・低の警告が残る（修正版は2.8.0、2.9.1、2.10.0、2.13.0）。CUDA 11.8版のPyTorchは2.7.1が最後なので、直すにはCUDA 12系の版へ移る必要がある。Seed-VCのtorch 2.10.0+cu128にも、低の警告が1件残る（修正版は2.13.0）。
