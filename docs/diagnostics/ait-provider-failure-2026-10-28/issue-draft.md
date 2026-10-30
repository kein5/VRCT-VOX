# bug(codex): child-to-parent messages abort turns in 0.1.20 — follow-up to #509

## Summary

On Ait Desktop/daemon 0.1.20 with Codex CLI 0.164.0, a child agent sending a message to its root parent is followed immediately by a parent poll failure and `Provider execution failed`. This interrupted ongoing work and prevented the expected child result from reaching the parent normally.

**This matches the already-merged fix in [PR #509](https://github.com/ait-app/ait/pull/509).** This report provides additional Linux observations and asks about stable-release availability; it does not claim that current main is still affected.

Checked on **2026-10-28 at 11:26 UTC / 20:26 JST**:

- #509 was merged at 05:32:54 UTC as `89ea11dd3724c1b08d33508c15d4531a1176d52d`.
- The latest public stable Release was still [v0.1.20](https://github.com/ait-app/ait/releases/tag/v0.1.20). Its documented rebuilt source, `bca1f98b8338f2bd6dbdd7f4e733337a564ce466`, does not contain the fix.
- Inspected main and [nightly](https://github.com/ait-app/ait/releases/tag/nightly) pointed to `7113431099355c59170bef9b825c92bd9b5d3f23`, whose source includes the fix.
- [PR #510](https://github.com/ait-app/ait/pull/510) and the [0.1.21 changelog](https://github.com/ait-app/ait/blob/7113431099355c59170bef9b825c92bd9b5d3f23/CHANGELOG.md#L3-L7) include this change. No public v0.1.21 Release was accessible at the time of checking. An unpublished draft may exist.

## Environment

| Component | Value |
| --- | --- |
| Ait during the recorded failures | Desktop / daemon 0.1.20, Linux AppImage |
| Provider | Codex CLI 0.164.0 |
| OS | CachyOS Linux, x86_64 |
| Kernel checked during investigation | 6.18.55-2-cachyos-lts |
| Time zone used by the user | Asia/Tokyo (UTC+09:00); logs below use UTC |

The precise source commit of the installed failing binary is unconfirmed. Version 0.1.20 alone does not identify it: the release notes distinguish the original tag from a later same-version rebuild. The relevant rejection branch is present in both published source variants.

## Observed behavior

Existing multi-agent work repeatedly stopped after a child sent a message to its parent. For one occurrence, the local Codex rollout and daemon log show:

| Time on 2026-10-28 (UTC) | Event |
| --- | --- |
| 10:25:04.163 | Child rollout records a completed `SubAgentActivity` with `kind=interacted`, `agent_path=/root`, and the root thread as its target |
| 10:25:04.173632 | Ait logs `Native provider observation failed`, provider `codex`, operation `poll` |
| 10:25:04.200903 | Ait records `Provider execution failed` for the parent turn, category `unknown`, source `session` |

The first daemon error occurs **10.632 ms** after the child event. Session identifiers below have been replaced; the error text and timestamps are retained.

```text
2026-10-28T10:25:04.173632Z  WARN provider::service::agent_manager::streaming: Native provider observation failed provider=codex agent_id=<parent-agent> operation="poll" error_kind=provider session operation failed
2026-10-28T10:25:04.200903Z ERROR provider::service::agent_manager::streaming: Native provider turn failed provider=codex agent_id=<parent-agent> turn_id="<parent-turn>" category="unknown" source="session" Provider execution failed
```

A prior metadata-only correlation pass found the same sequence for **five of seven recorded poll failures** in this parent session on that date:

| Child event (UTC) | Poll failure (UTC) | Gap |
| --- | --- | ---: |
| 05:38:41.744 | 05:38:41.753499 | 9.499 ms |
| 06:01:07.734 | 06:01:07.748356 | 14.356 ms |
| 06:09:06.025 | 06:09:06.030836 | 5.836 ms |
| 09:25:07.565 | 09:25:07.589022 | 24.022 ms |
| 10:25:04.163 | 10:25:04.173632 | 10.632 ms |

The other two failures were not attributed to this cause. This is a correlation among recorded failures, **not** a failure rate across all messages or a controlled reproduction count.

## Minimal reproduction to try

The following reduces the observed workflow. It has **not been rerun as a fresh live-model reproduction** during this investigation.

1. Use an isolated Ait session with the affected 0.1.20 provider implementation and Codex CLI 0.164.0, with native child-agent tools available.
2. Ask the parent to spawn one child with this instruction:

   ```text
   Send a short "ready" message to your parent using
   collaboration.send_message(target="/root", message="ready"), then finish.
   Do not read or modify any files.
   ```

3. Keep the parent turn active while waiting for the child.
4. Observe the child activity and the parent outcome. The suspected trigger is the child-to-root `interacted` event, not child creation alone.

Expected: the parent receives the message and can continue or finish normally. Sending a message should not create a new child relationship or reparent an existing thread.

Actual in the recorded workflow: the parent poll fails and the turn ends with a generic provider error.

For deterministic adapter testing, first register a child through a valid native start event, then feed the following **illustrative, anonymized RPC-shaped event** while its parent is active:

```json
{
  "method": "item/completed",
  "params": {
    "threadId": "child-thread",
    "turnId": "child-turn",
    "item": {
      "id": "child-message",
      "type": "subAgentActivity",
      "kind": "interacted",
      "agentThreadId": "root-thread",
      "agentPath": "/root"
    }
  }
}
```

This is not a verbatim captured RPC frame. The local evidence is a Codex rollout item, which uses `SubAgentActivity` and snake_case fields. The example uses the adapter's camelCase RPC form. PR #509 already adds an offline integration fixture for this sequence.

## Diagnosis and existing fix

In the [original v0.1.20 code](https://github.com/ait-app/ait/blob/98503c93c1288855b2248cb3f96eac2df2a368bd/crates/provider/src/local/codex/subagents.rs#L37-L45) and the [rebuilt 0.1.20 source](https://github.com/ait-app/ait/blob/bca1f98b8338f2bd6dbdd7f4e733337a564ce466/crates/provider/src/local/codex/subagents.rs#L37-L45), `Live::activity` rejects an event when its receiver is the root context, before distinguishing creation from communication. A valid child-to-root interaction therefore matches that rejection branch.

PR #509 separates communication from child enrollment. Its author reports that the offline parent-return regression failed before the change and that 12 targeted tests passed afterward. Those results belong to the upstream PR; I did not run its test suite locally.

The local timing, source branch, and upstream regression strongly support this explanation. However, I have not instrumented the running daemon to prove the exact return site, replayed the original RPC stream, or tested an updated installer against the affected session.

This is separate from the large-history problem in [Issue #491](https://github.com/ait-app/ait/issues/491), addressed by [PR #492](https://github.com/ait-app/ait/pull/492) and listed in [v0.1.19](https://github.com/ait-app/ait/releases/tag/v0.1.19).

## Stable-release follow-up

Could you confirm which public stable installer/daemon build first includes #509, and how an existing 0.1.20 installation should obtain it?

The 0.1.20 release page describes a same-version rebuild, but its documented source predates #509. Reinstalling that rebuild therefore would not include this fix. I have not installed or tested nightly; its source inclusion is not a claim of Linux end-to-end acceptance.

Until a fixed build is installed and verified, I am keeping this workflow in the parent agent to avoid triggering child-to-parent messaging.

No private project content, message payloads, credentials, actual session identifiers, or machine-specific paths are included in this report. Ait was not updated, restarted, or patched during this investigation.
