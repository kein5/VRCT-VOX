# Contributing to VRCT-VOX

Issues and pull requests are welcome in English or Japanese. Report security vulnerabilities privately as described in [SECURITY.md](SECURITY.md).

## Branches and releases

| Branch | Purpose | Releases |
|---|---|---|
| `develop` | Integration branch; open pull requests here | Betas, `X.Y.Z-beta.N` (GitHub prereleases) |
| `main` | Protected; changes arrive only by pull request | Stable releases, `X.Y.Z` |

Create a topic branch from `develop` (for example `fix/quick-chat-focus`) and open a pull request to `develop`.

A stable release starts from a `release/X.Y.Z` branch cut from `develop` whose only changes are the version (`X.Y.Z`, set with `utils/update_version.py`) and its CHANGELOG section. Its pull request to `main` must pass the required checks; after the release, `main` is merged back into `develop` and `develop` moves to the next `-beta.N`. See [Changelog and releases](#changelog-and-releases) and [release candidates](docs/voice-stack/release-candidates.md).

## Pull requests

- Write every commit message as a [Conventional Commit](#commit-messages). The commit-msg hook and CI check them.
- Add or update tests for behavior changes, and describe what you verified and what you could not.
- Do not commit secrets, API keys, voice recordings or model files without a redistribution license.
- New or upgraded dependencies must have a compatible license; update [NOTICE.md](NOTICE.md) when bundled components change. Python dependencies live in `pyproject.toml` and `uv.lock` (`uv lock`).
- Models offered for download go into the download catalog (`src-python/models/model_downloads/catalog.py`) with a pinned revision, file sizes, SHA-256 and the license shown before download. Do not make a model with a non-commercial or otherwise restrictive license a default.
- User-facing text goes into `locales/`. English (`en.yml`) and Japanese (`ja.yml`) are the only UI languages; update both. Korean and Chinese were dropped as UI languages in 0.2.0 (they remain translation languages).
- Icons and logos are generated from `docs/brand/` with `tools/brand_assets.py`; edit the sources there, not the generated files.

Automated checks on every pull request: the model-free contract tests on Linux and Windows, the commit-message check, dependency review (known vulnerabilities and licenses), and CodeQL code scanning. Pull requests to `main` must pass the required checks before merging.

## Commit messages

Commit messages follow [Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/). The same rules apply to people and to AI agents ([AGENTS.md](AGENTS.md)).

```text
<type>(<scope>)!: <summary>

<body: what changed and why>

<footers, such as BREAKING CHANGE: or Changelog:>
```

- Write the summary as one line in English, in the imperative, starting in lower case, with no period. Say what changed for the person affected: `fix(tts): keep the queue when the server restarts`, not `fix: bug`.
- The scope is optional and names the area, such as `tts`, `asr`, `rvc`, `ocr`, `ui`, `flow`, `site`, `dev`, `ci` or `deps`.
- Mark a breaking change with `!` after the type or scope, and add a `BREAKING CHANGE:` footer that says what users or developers must do. A change is breaking when a setting, a file format, an IPC or OSC contract, or a supported platform stops working as before.

| Type | Use it for | CHANGELOG heading |
|---|---|---|
| `feat` | Something new that users can do | Features |
| `fix` | A bug users could hit | Bug Fixes |
| `perf` | Faster or lighter, with the same behavior | Performance |
| `refactor` | Code reorganized, with the same behavior | Refactoring |
| `docs` | Documentation, the user guide included | Documentation |
| `test` | Tests only | Tests |
| `build` | Packaging, bundles, dependencies (`build(deps)`) | Build & CI, Dependencies |
| `ci` | GitHub Actions | Build & CI |
| `chore` | Upkeep that fits nothing above | Maintenance |
| `style` | Formatting only | Maintenance |
| `revert` | Undoing an earlier commit (`revert: <its summary>`) | Maintenance |

Examples:

```text
feat(asr): label who speaks in game audio captions
fix(ui)!: accept only English and Japanese as UI languages

BREAKING CHANGE: UI_LANGUAGE accepts only "en" and "ja".
build(deps): update tauri
docs(site): add the page on using your own models

Changelog: user
```

### The commit-msg hook

The hook rejects a message that is not a Conventional Commit before the commit is made. It is defined in [`cog.toml`](cog.toml) and installed per clone:

1. Install [Cocogitto](https://docs.cocogitto.io/) 7 (`cargo install cocogitto --version 7.0.0 --locked`, or your package manager), so that `cog --version` prints `cog 7.x`.
2. In the repository, run `cog install-hook commit-msg`. It writes `.git/hooks/commit-msg`, which every worktree of the clone shares.
3. After `cog.toml` changes the hook, run `cog install-hook commit-msg --overwrite`.

Merge commits pass, as `cog check` ignores them. `fixup!`, `squash!` and `amend!` commits pass locally so that `git rebase --autosquash` keeps working; squash them before you open a pull request, because CI rejects them. To check a message by hand, run `cog verify "feat(ui): ..."`.

CI checks the commits of every pull request, and the commits pushed to `develop` and `main`, with `python tools/dev.py check --scope commits --base <base>`. Old history is not rewritten.

## Changelog and releases

[`CHANGELOG.md`](CHANGELOG.md) is the record of what each release changed. It is written once per release, when the release is prepared, not on every commit. Do not edit it in a feature branch.

### Preparing a release

1. Set the version in `package.json` (`X.Y.Z-beta.N` on `develop`, `X.Y.Z` on a `release/X.Y.Z` branch) and run `npm run update-version`.
2. Run `npm run changelog` (`python tools/changelog.py write`). It reads the commits since the nearest earlier release tag (`v*`) through Cocogitto and adds the version's section at the top of `CHANGELOG.md`. Run `python tools/changelog.py print` to see the section without writing it.
3. Read the section. If a line is unclear, fix it in the file; the tool will not overwrite a section that differs from what it would write unless you pass `--force`.
4. Commit both as `chore(release): version X.Y.Z` and open the pull request. Release pull requests to `main` fail if the section is missing.
5. Build the candidates and run "Prepare verified VRCT-VOX release draft" ([release candidates](docs/voice-stack/release-candidates.md)). The draft's notes are made from the CHANGELOG section.
6. Before publishing the draft, write its Highlights, Upgrade Notes and Known Issues. Publishing creates the `vX.Y.Z` tag.

Running `write` again gives the same file. It stops if the tag `vX.Y.Z` already exists. Tags are created only by publishing a GitHub release; do not run `cog bump` and do not push tags by hand.

### What goes where

Each section lists "User-facing Changes" first and "Internal Changes" after. Headings without entries are left out.

| Group | Heading | Commits |
|---|---|---|
| User-facing | Breaking Changes | Any commit with `!` or `BREAKING CHANGE:` |
| User-facing | Features | `feat` |
| User-facing | Improvements | Other types marked `Changelog: user` |
| User-facing | Bug Fixes | `fix` |
| User-facing | Performance | `perf` |
| User-facing | Security | `fix(security)`, or any commit marked `Changelog: security` |
| Internal | Refactoring | `refactor` |
| Internal | Dependencies | any type with the `deps` scope |
| Internal | Build & CI | `build`, `ci`, and `feat`/`fix` with the `ci` or `build` scope |
| Internal | Tests | `test`, and `feat`/`fix` with the `test` or `tests` scope |
| Internal | Documentation | `docs` |
| Internal | Maintenance | `chore`, `style`, `revert`, and `feat`/`fix` with the `dev` or `tooling` scope |

Start from the type, then check what the change does for users. Add a `Changelog:` footer when the type alone would put a commit in the wrong place:

- `Changelog: user` lists it under User-facing (for example a dependency update that fixes a crash users see).
- `Changelog: security` lists it under Security.
- `Changelog: internal` keeps a `feat` or `fix` that only developers notice out of the user-facing headings.
- `Changelog: skip` leaves it out (noise such as a typo in a test name).

Release commits (`chore(release): ...`) and merge commits are left out. The same summary twice becomes one line with both commits linked.

### GitHub Releases

The CHANGELOG section is the full list; the GitHub release helps users decide whether to update. Its draft starts with Highlights, Breaking Changes (copied from the section), Upgrade Notes and Known Issues, then the user-facing changes. Internal changes are counted and linked to `CHANGELOG.md`. A stable release's draft also lists the user-facing changes of the pre-releases it includes, since its users may come straight from the previous stable release. Keep the two consistent: change the CHANGELOG first, then the release text.

### Troubleshooting

- If the hook says Cocogitto is not installed, install Cocogitto 7 or make `cog` reachable from Git's shell (the hook also tries `mise exec -- cog`). To stop checking in this clone, delete `.git/hooks/commit-msg`.
- If `cog install-hook` refuses to replace a hook, another hook is already there. Check it, then add `--overwrite`.
- If CI rejects a commit that the hook let through, it is a `fixup!`, `squash!` or `amend!` commit, or it was made without the hook. Rewrite your branch with `git rebase -i` before it is merged; never rewrite `develop` or `main`.
- If the tool reports `changelog: no earlier release tag`, fetch the tags with `git fetch --tags`.
- If it reports `CHANGELOG.md already has a different section`, new commits arrived after you wrote the section, or someone edited it. Compare it with the output of `print`, then run `write --force`.

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

Issue や PR は日本語でも構いません。作業ブランチは `develop` から作り、PR は `develop` へ出してください。`main` は保護されています。正式版のときだけ、`develop` から切った `release/X.Y.Z` ブランチ（版の変更と CHANGELOG の節だけ）を PR で統合します。

- コミットは Conventional Commits の形式で書きます。種別の選び方と例は上の「Commit messages」にあります。
- 形式の検査は commit-msg フックで行います。Cocogitto 7 を入れて、複製ごとに `cog install-hook commit-msg` を一度実行してください。CI も PR と、develop・main への push を検査します。
- `CHANGELOG.md` はリリースを準備するときに `npm run changelog` で書きます。機能のブランチでは編集しません。手順と分類は上の「Changelog and releases」にあります。
- テストと確認した内容を PR に書いてください。
- 表示する文言は `locales/` の英語と日本語の両方に足します。
- ダウンロードできるモデルは、版・サイズ・SHA-256・ライセンスを固定してカタログに登録します。非商用ライセンスのモデルは既定にしません。

脆弱性は SECURITY.md の手順で非公開に報告してください。
