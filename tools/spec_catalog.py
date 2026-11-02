#!/usr/bin/env python3
"""Generate the reference catalogs of the functional specification from source.

The tables under docs/spec/reference/ list every IPC endpoint, error code and
config key. They are read from the code (mainloop.py, errors.py, config.py and
the UI route definitions), so they cannot drift from it unnoticed:

    python tools/spec_catalog.py --write   # regenerate the tables
    python tools/spec_catalog.py --check   # exit 1 when they are out of date

The parsing is static (ast and regular expressions); nothing is imported or run.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "spec" / "reference"
PY = ROOT / "src-python"
UI = ROOT / "src-ui" / "logics"

HEADER = (
    "<!-- 自動生成。手で編集しない。`python tools/spec_catalog.py --write`で更新する。 -->\n"
)


def cell(value: object) -> str:
    text = "" if value is None else str(value)
    return re.sub(r"\s+", " ", text).replace("|", "\\|").strip()


def code(value: object) -> str:
    text = cell(value)
    return f"`{text}`" if text else ""


def table(head: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines) + "\n"


def module_dict(tree: ast.Module, name: str) -> ast.Dict:
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        if any(isinstance(t, ast.Name) and t.id == name for t in targets) and isinstance(node.value, ast.Dict):
            return node.value
    raise SystemExit(f"{name} not found")


# --- IPC endpoints -------------------------------------------------------------

def ui_routes() -> dict[str, str]:
    """Endpoint -> UI handler, mirroring buildRouteMetaList() in useReceiveRoutes.js."""
    routes_js = (UI / "useReceiveRoutes.js").read_text(encoding="utf-8")
    setter_js = (UI / "configs" / "config_page_setter" / "ui_config_setter.js").read_text(encoding="utf-8")
    routes: dict[str, str] = {}
    static = re.findall(r'\{\s*endpoint:\s*"([^"]+)",\s*ns:\s*\w+,\s*hook_name:\s*(?:"(\w+)"|null),\s*method_name:\s*(?:"(\w+)"|null)', routes_js)
    for endpoint, hook, method in static:
        routes[endpoint] = f"{hook}.{method}" if hook else "（受け取るだけ）"

    def add(endpoint: str, hook: str, method: str) -> None:
        routes.setdefault(endpoint, f"{hook}.{method}")

    # One entry per `Category:`; default values may hold nested braces.
    starts = [m.start() for m in re.finditer(r"\bCategory:", setter_js)]
    for start, end in zip(starts, starts[1:] + [len(setter_js)]):
        block = setter_js[start:end]
        field = lambda key: (re.search(rf'{key}:\s*"([^"]+)"', block) or [None, None])[1]
        base, ep, logics, ui_template = field("Base_Name"), field("base_endpoint_name"), field("logics_template_id"), field("ui_template_id")
        category = field("Category")
        if not (base and ep and category):
            continue
        hook = f"use{category}"
        if '"from_backend"' in block:
            add(f"/run/{ep}", hook, f"updateFromBackend{base}")
        add(f"/get/data/{ep}", hook, f"updateFromBackend{base}")
        if logics == "get_set_delete":
            add(f"/delete/data/{ep}", hook, f"deleteSuccess{base}")
        if logics not in ("get_list", "get_only"):
            add(f"/set/data/{ep}", hook, f"setSuccess{base}")
        if logics == "toggle_enable_disable" or ui_template == "toggle":
            add(f"/set/enable/{ep}", hook, f"setSuccess{base}")
            add(f"/set/disable/{ep}", hook, f"setSuccess{base}")
        if logics == "weight_download_status":
            add(f"/get/data/selectable_{ep}_type_dict", hook, f"updateDownloaded{base}")
            add(f"/run/download_progress_{ep}", hook, f"updateDownloadProgress{base}")
            add(f"/run/downloaded_{ep}", hook, f"downloaded{base}")
            add(f"/run/pending_{ep}", hook, f"pending{base}")
            add(f"/run/download_{ep}", hook, f"downloaded{base}")
    return routes


def kind_of(endpoint: str) -> str:
    for prefix, label in (("/get/data/", "取得"), ("/set/data/", "設定"), ("/delete/data/", "削除"),
                          ("/set/enable/", "有効化"), ("/set/disable/", "無効化"), ("/run/", "実行")):
        if endpoint.startswith(prefix):
            return label
    return "その他"


def sensitive_markers() -> tuple[str, ...]:
    tree = ast.parse((PY / "utils.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "SENSITIVE_ENDPOINT_MARKERS" for t in node.targets):
            return tuple(ast.literal_eval(node.value))
    raise SystemExit("SENSITIVE_ENDPOINT_MARKERS not found")


def immediate_endpoints(tree: ast.Module) -> set[str]:
    """Requests the receiver answers at once instead of queueing (Main.receiver)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Set):
            values = {e.value for e in node.elts if isinstance(e, ast.Constant)}
            if "/run/stop_voice" in values:
                return values
    return set()


def render_endpoints() -> str:
    tree = ast.parse((PY / "mainloop.py").read_text(encoding="utf-8"))
    mapping = module_dict(tree, "mapping")
    run_mapping = module_dict(tree, "run_mapping")
    routes = ui_routes()
    markers = sensitive_markers()
    immediate = immediate_endpoints(tree)

    requests = []
    for key, value in zip(mapping.keys, mapping.values):
        endpoint = key.value
        fields = {k.value: v for k, v in zip(value.keys, value.values)}
        handler = fields["variable"]
        handler_name = handler.attr if isinstance(handler, ast.Attribute) else ast.unparse(handler)
        before_init = "可" if isinstance(fields["status"], ast.Constant) and fields["status"].value else "待つ"
        notes = []
        if endpoint in immediate:
            notes.append("即時（キューを通らない）")
        if any(m in endpoint.lower() for m in markers):
            notes.append("ログで伏せる")
        requests.append([code(endpoint), kind_of(endpoint), code(handler_name), before_init,
                         cell(routes.get(endpoint, "—")), cell("、".join(notes))])

    pushes = []
    for key, value in zip(run_mapping.keys, run_mapping.values):
        endpoint = value.value
        pushes.append([code(key.value), code(endpoint), cell(routes.get(endpoint, "—"))])

    request_set = {k.value for k in mapping.keys}
    push_set = {v.value for v in run_mapping.values}
    unrouted = sorted((request_set | push_set) - set(routes))
    ui_only = sorted(e for e in routes if e not in request_set | push_set)

    kinds = {}
    for row in requests:
        kinds[row[1]] = kinds.get(row[1], 0) + 1
    summary = "、".join(f"{k} {n}" for k, n in sorted(kinds.items()))

    out = [HEADER, "# IPCエンドポイント一覧\n",
           "UIからサイドカーへの要求（`mapping`）と、サイドカーからUIへの通知（`run_mapping`）の一覧。"
           "メッセージの形、状態コード、ロックと再試行の規則は[IPCプロトコル](../ipc-protocol.md)にある。\n",
           "列の意味:\n",
           "- 初期化前: 「待つ」は初期化が終わるまでロックされる要求（サイドカーが約30秒まで入れ直し、解けなければ423を返す）。「可」は起動直後から受け付ける。",
           "- UIの受信先: 200の応答を処理するUIのフック（`useReceiveRoutes.js`の静的ルートと`ui_config_setter.js`の定義から生成）。「—」は受信先がない。",
           "- ログで伏せる: `process.log`で値を`***MASKED***`に置き換える（`SENSITIVE_ENDPOINT_MARKERS`）。stdoutのIPCそのものは伏せない。\n",
           f"## 要求（{len(requests)}件: {summary}）\n",
           table(["エンドポイント", "種別", "処理（controller）", "初期化前", "UIの受信先", "備考"], requests),
           f"\n## 通知（サイドカーからUIへ、{len(pushes)}件）\n",
           "要求への応答とは別に、サイドカーが自分から送るメッセージ。`controller.run(status, run_mapping[名前], result)`で送る。\n",
           table(["名前", "エンドポイント", "UIの受信先"], pushes),
           f"\n## UIに受信先がないエンドポイント（{len(unrouted)}件）\n",
           "200で届いた場合にUIが`Invalid endpoint`としてコンソールに出すもの。ただし、400で届くエラーの通知（`/run/error_…`など）は`errorHandling_Backend`が処理し、"
           "`/run/initialization_complete`は`receiveRoutes`が個別に処理するので、このどちらかに当たるものは実害がない。\n",
           "".join(f"- {code(e)}\n" for e in unrouted) or "なし\n",
           f"\n## UIだけにあるルート（{len(ui_only)}件）\n",
           "UIに受信先が定義されているが、サイドカーの`mapping`と`run_mapping`にはないもの。多くは`ui_config_setter.js`の定義が機械的に作るルートで、使われない。\n",
           "".join(f"- {code(e)}\n" for e in ui_only) or "なし\n"]
    return "\n".join(out)


# --- error codes ----------------------------------------------------------------

def class_constants(tree: ast.Module, name: str) -> dict[str, str]:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return {t.id: s.value.value for s in node.body if isinstance(s, ast.Assign)
                    for t in s.targets if isinstance(t, ast.Name) and isinstance(s.value, ast.Constant)}
    raise SystemExit(f"class {name} not found")


def render_errors() -> str:
    tree = ast.parse((PY / "errors.py").read_text(encoding="utf-8"))
    codes = class_constants(tree, "ErrorCode")
    categories = class_constants(tree, "ErrorCategory")
    metadata = module_dict(tree, "ERROR_METADATA")
    handler_js = (UI / "_useBackendErrorHandling.js").read_text(encoding="utf-8")
    handled = set(re.findall(r'case "([A-Z0-9_]+)"', handler_js)) | set(re.findall(r"^\s+([A-Z0-9_]+):\s*\"common_error", handler_js, re.M))

    rows, described = [], set()
    for key, value in zip(metadata.keys, metadata.values):
        name = key.attr
        described.add(name)
        fields = {k.value: v for k, v in zip(value.keys, value.values)}
        category = fields.get("category")
        category = categories.get(category.attr, category.attr) if isinstance(category, ast.Attribute) else ""
        literal = lambda f: fields[f].value if f in fields and isinstance(fields[f], ast.Constant) else ""
        rows.append([code(codes.get(name, name)), cell(category), cell(literal("message")), cell(literal("severity")),
                     "要" if literal("user_action_required") is True else "", "あり" if codes.get(name, name) in handled else ""])
    missing = sorted(set(codes) - described)

    out = [HEADER, "# エラーコード一覧\n",
           "`src-python/errors.py`の`ErrorCode`と`ERROR_METADATA`から生成した。"
           "応答の形とUIでの見せ方は[横断的な振る舞い](../cross-cutting.md#エラーの扱い)にある。\n",
           "- 既定メッセージ: サイドカーが返す英語の`message`。UIは多くの場合`locales/`の文言に置き換えて表示する。",
           "- UIの個別処理: `_useBackendErrorHandling.js`に専用の分岐（値の巻き戻しや翻訳した文言の表示）がある。"
           "空欄のコードは、音声やモデル取得など別の経路で処理されるか、汎用の通知になる。\n",
           f"## コード（{len(rows)}件）\n",
           table(["コード", "分類", "既定メッセージ", "重大度", "利用者の対処", "UIの個別処理"], rows)]
    if missing:
        out += [f"\n## メタデータのないコード（{len(missing)}件）\n", "既定メッセージは`GENERAL_UNKNOWN`のものになる。\n",
                "".join(f"- {code(codes[m])}\n" for m in missing)]
    return "\n".join(out)


# --- config keys -----------------------------------------------------------------

def render_config() -> str:
    tree = ast.parse((PY / "config.py").read_text(encoding="utf-8"))
    config = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Config")
    defaults: dict[str, str] = {}
    for node in ast.walk(config):
        if isinstance(node, ast.FunctionDef) and node.name == "init_config":
            for stmt in ast.walk(node):
                if isinstance(stmt, ast.Assign):
                    for target in stmt.targets:
                        if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) \
                                and target.value.id == "self" and target.attr.startswith("_"):
                            defaults.setdefault(target.attr[1:], ast.unparse(stmt.value))

    persisted, runtime = [], []
    for stmt in config.body:
        if not (isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Call) and isinstance(stmt.value.func, ast.Name)):
            continue
        kind = stmt.value.func.id
        if kind not in ("ManagedProperty", "ValidatedProperty"):
            continue
        name = stmt.targets[0].id
        kw = {k.arg: k.value for k in stmt.value.keywords}
        flag = lambda key, default=False: kw[key].value if key in kw and isinstance(kw[key], ast.Constant) else default
        if kind == "ManagedProperty":
            type_ = ast.unparse(kw["type_"]) if "type_" in kw else ""
            check = type_ + (f"、許可値 {ast.unparse(kw['allowed'])}" if "allowed" in kw else "")
        else:
            validator = stmt.value.args[1] if len(stmt.value.args) > 1 else kw.get("validator")
            check = f"検証 {ast.unparse(validator)}" if validator is not None else "検証"
        default = defaults.get(name, "")
        if len(default) > 90:
            default = default[:87] + "…"
        save = "即時" if flag("immediate_save") else "2秒後にまとめて"
        row = [code(name), cell(check), code(default)]
        if flag("readonly"):
            runtime.append(row + ["読み取り専用"])
        elif flag("serialize", True):
            persisted.append(row + [save])
        else:
            runtime.append(row + ["保存しない"])

    out = [HEADER, "# 設定キー一覧\n",
           "`src-python/config.py`の`Config`クラス（`ManagedProperty`と`ValidatedProperty`）と`init_config()`の既定値から生成した。"
           "保存の仕組み（2秒の遅延、置き換えによる書き込み、読み込み時の検証）は[データ形式と保存](../data-and-persistence.md)にある。\n",
           f"## config.jsonに保存するキー（{len(persisted)}件）\n",
           table(["キー", "型・検証", "既定値", "保存"], persisted),
           f"\n## 保存しないキー（{len(runtime)}件）\n",
           "実行中だけの状態、選択肢の一覧、読み取り専用の値。起動のたびに既定値や検出結果から作り直す。\n",
           table(["キー", "型・検証", "既定値", "扱い"], runtime)]
    return "\n".join(out)


CATALOGS = {
    "ipc-endpoints.md": render_endpoints,
    "error-codes.md": render_errors,
    "config-keys.md": render_config,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="regenerate docs/spec/reference/")
    mode.add_argument("--check", action="store_true", help="exit 1 when docs/spec/reference/ is out of date")
    args = parser.parse_args()

    stale = []
    for name, render in CATALOGS.items():
        path = OUT / name
        text = render()
        if args.write:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            print(f"wrote {path.relative_to(ROOT)}")
        elif not path.exists() or path.read_text(encoding="utf-8") != text:
            stale.append(str(path.relative_to(ROOT)))
    if stale:
        print("Out of date (run `python tools/spec_catalog.py --write`): " + ", ".join(stale), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
