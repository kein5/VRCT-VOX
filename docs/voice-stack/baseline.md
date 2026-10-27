# P0 baseline (2026-10-27)

- HEAD: `79419a1f2ce78d38993b0f33e273155667eb0b6a`、開始時worktree clean。
- Windows中心のReact 18.3.1 / Vite 6.3.4 / Tauri 2.5.1。
- Host: Linux、system Python 3.14.8、uv選択venv Python 3.13.17、Node 26.12.1、npm 11.20.0、Cargo 1.99.1。
- `node --test src-ui/logics/main/*.test.js src-ui/logics/common/*.test.js`: 既存4ファイルPASS。
- 当初pytest/Vite未導入。`uv venv .venv`、`uv pip install --python .venv/bin/python pytest==8.4.2 requests==2.34.2 PyYAML==6.0.2 ruff==0.14.4` と `npm ci --ignore-scripts` で軽量検証環境を準備。
- 変更前 `npm run vite-build`: FAIL、既存importは `vrct.svg`、実ファイルは `VRCT.svg`。Linuxの大小文字区別による不一致。
- 軽量依存導入後の変更前pytest全体: 80 collection errors（psutil、numpy、openvr等の未導入依存）。Windows用の全依存はLinuxへ強制導入していない。
- `CARGO_TARGET_DIR=/tmp/vrct-target cargo check --offline --manifest-path src-tauri/Cargo.toml`: FAIL、font-kitがローカルcacheにない。Tauri/NSIS完全ビルド未検証。
- `pw-cat --help`: 利用可。`pw-cli info 0`: sandboxから接続不可。
- `nvidia-smi`: NVIDIA driverとの通信失敗。モデル、VRChat、HMDのE2Eは未検証。

新しいheadlessテストは既存Windows conftestを読み込まない独立suiteとする。
既存suiteは置き換えず、収集不能をPASSと報告しない。
再現コマンド・実測結果は [phase-report.md](phase-report.md) に追記する。
