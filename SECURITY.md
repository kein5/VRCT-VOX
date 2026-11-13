# Security policy

## Supported versions

| Version | Supported |
|---|---|
| Latest stable release (from `main`) | Yes |
| Latest beta release (from `develop`) | Yes, until the next beta or stable release |
| Older releases and unreleased builds | No |

## Scope

In scope: the VRCT-VOX application and its Python sidecar, the Windows installer and Linux packages (AppImage, tar.gz) published on [Releases](https://github.com/kein5/VRCT-VOX/releases), the local servers the app opens (for example the OBS browser source and the WebSocket server), model download and verification, and the release workflows in this repository.

Out of scope: vulnerabilities in third-party engines and models (speech.cpp, RVC, Seed-VC, translation and speech services) that VRCT-VOX does not change. Report those to their projects; tell us too if VRCT-VOX should work around them. VRCT-VOX is derived from [VRCT](https://github.com/misyaguziya/VRCT); if an issue also affects upstream VRCT, report it to its maintainers as well.

## Reporting a vulnerability

Please report vulnerabilities privately through GitHub: open the repository's **Security** tab and choose **Report a vulnerability** ([private vulnerability reporting](https://github.com/kein5/VRCT-VOX/security/advisories/new)). Do not open a public issue for a vulnerability.

Include the affected version and operating system, the steps to reproduce, and the impact you expect. Remove personal data such as voice recordings, chat text, API keys and full log files you have not reviewed.

This project is maintained by one person on a best-effort basis. We aim to acknowledge a report within 7 days, and we publish a fix in a new release (released assets are never replaced) together with a GitHub security advisory when the issue is confirmed.

## 脆弱性の報告（日本語）

脆弱性は公開の Issue ではなく、リポジトリの **Security** タブの **Report a vulnerability**（非公開の脆弱性報告）から報告してください。影響を受ける版と OS、再現手順、想定される影響を書き、音声・チャット本文・API キーなどの個人情報は取り除いてください。

対象は、VRCT-VOX のアプリ本体と Python のバックエンド、Releases で配布しているインストーラーと Linux 版のパッケージ、アプリが開くローカルのサーバー、モデルの取得と検証、このリポジトリのリリース用ワークフローです。speech.cpp などの外部エンジンやモデル自体の問題はそれぞれのプロジェクトへ報告してください。本家 VRCT にも影響する問題は、本家の開発者にも伝えてください。

サポート対象は、最新の正式版（`main` から公開）と最新のベータ版（`develop` から公開）です。報告には 7 日以内の受領連絡を目標にし、確認できた問題は新しい版で修正して GitHub のセキュリティアドバイザリで公表します。公開済みのファイルを差し替えることはありません。
