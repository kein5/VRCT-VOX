# Contributing to VRCT-VOX

Issues and pull requests are welcome in English or Japanese. Report security vulnerabilities privately as described in [SECURITY.md](SECURITY.md).

## Branches and releases

| Branch | Purpose | Releases |
|---|---|---|
| `develop` | Integration branch; open pull requests here | Betas, `X.Y.Z-beta.N` (GitHub prereleases) |
| `main` | Protected; changes arrive only by pull request | Stable releases, `X.Y.Z` |

Create a topic branch from `develop` (for example `fix/quick-chat-focus`) and open a pull request to `develop`.

A stable release starts from a `release/X.Y.Z` branch cut from `develop` whose only change is the version (`X.Y.Z`, set with `utils/update_version.py`). Its pull request to `main` must pass the required checks; after the release, `main` is merged back into `develop` and `develop` moves to the next `-beta.N`. See [release candidates](docs/voice-stack/release-candidates.md).

## Pull requests

- Follow [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) (`feat:`, `fix:`, `docs:`, `build(deps):` ...). CI checks the new commits.
- Add or update tests for behavior changes, and describe what you verified and what you could not.
- Do not commit secrets, API keys, voice recordings or model files without a redistribution license.
- New or upgraded dependencies must have a compatible license; update [NOTICE.md](NOTICE.md) when bundled components change. Python dependencies live in `pyproject.toml` and `uv.lock` (`uv lock`).
- Models offered for download go into the download catalog (`src-python/models/model_downloads/catalog.py`) with a pinned revision, file sizes, SHA-256 and the license shown before download. Do not make a model with a non-commercial or otherwise restrictive license a default.
- User-facing text goes into `locales/`. English (`en.yml`) and Japanese (`ja.yml`) are required; add Korean and Chinese (`ko.yml`, `zh-Hant.yml`, `zh-Hans.yml`) where you can, otherwise the English text is shown.
- Icons and logos are generated from `docs/brand/` with `tools/brand_assets.py`; edit the sources there, not the generated files.

Automated checks on every pull request: the model-free contract tests on Linux and Windows, the commit-message check, dependency review (known vulnerabilities and licenses), and CodeQL code scanning. Pull requests to `main` must pass the required checks before merging.

## Local setup and checks

See [docs/development.md](docs/development.md):

```sh
python tools/dev.py doctor
python tools/dev.py setup --scope headless
python tools/dev.py check --scope voice
```

## Relationship to VRCT

VRCT-VOX is derived from [VRCT](https://github.com/misyaguziya/VRCT) and no longer tracks it. Send changes for VRCT-VOX here; report problems in upstream VRCT to its maintainers, and do not send them VRCT-VOX support requests.

## 日本語での概要

Issue や PR は日本語でも構いません。作業ブランチは `develop` から作り、PR は `develop` へ出してください。`main` は保護されていて、正式版のときだけ `develop` から切った `release/X.Y.Z` ブランチ（版の変更のみ）を PR で統合します。コミットは Conventional Commits の形式で書き、テストと確認内容を PR に記載してください。表示する文言は `locales/` の英語と日本語に必ず追加し、ダウンロードできるモデルは版・サイズ・SHA-256・ライセンスを固定してカタログに登録してください。非商用ライセンスのモデルは既定にしません。脆弱性は SECURITY.md の手順で非公開に報告してください。
