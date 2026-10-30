#!/usr/bin/env python3
"""Coordinate existing Ait sessions in this workspace through the local MCP API."""

import argparse
import ipaddress
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.request
import uuid


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("Refusing to redirect an authenticated local request")


class AitClient:
    def __init__(self, data_dir, caller_id=None):
        self.data_dir = data_dir.resolve()
        rows = json.loads((self.data_dir / "agents/agents.json").read_text())
        session_id = os.environ.get("CODEX_SESSION_ID")
        matches = [a for a in rows if (
            a["id"] == caller_id if caller_id else
            bool(session_id) and (a.get("persistence") or {}).get("sessionId") == session_id
        )]
        if len(matches) != 1:
            raise RuntimeError("Cannot identify this session; provide --caller-id from Ait")
        self.caller = matches[0]
        if Path(self.caller["cwd"]).resolve() != Path.cwd().resolve():
            raise RuntimeError("Run from the caller session's workspace root")
        candidates = []
        for process in Path("/proc").glob("[0-9]*"):
            try:
                if process.stat().st_uid != os.getuid():
                    continue
                argv = (process / "cmdline").read_bytes().split(b"\0")
                if b"--data-dir" not in argv or b"--listen" not in argv:
                    continue
                directory = Path(os.fsdecode(argv[argv.index(b"--data-dir") + 1]))
                if directory.resolve() == self.data_dir:
                    candidates.append((process, argv))
            except (OSError, ValueError, IndexError):
                continue
        if len(candidates) != 1:
            raise RuntimeError("Cannot identify one local Ait daemon; host process/network access may be required")
        process, argv = candidates[0]
        address = argv[argv.index(b"--listen") + 1].decode()
        host, port = address.rsplit(":", 1)
        if not ipaddress.ip_address(host.strip("[]")).is_loopback or not 0 < int(port) < 65536:
            raise RuntimeError("Only a loopback daemon address is supported")
        # Desktop supplies this credential to its daemon. Never print or persist it.
        environment = dict(item.split(b"=", 1) for item in
                           (process / "environ").read_bytes().split(b"\0") if b"=" in item)
        token = environment.get(b"AIT_SERVER_TOKEN")
        if not token:
            # New Desktop daemons store the same local API credential in a file.
            # It stays in memory and is sent only to the verified loopback daemon.
            credential = self.data_dir / "local-api.token"
            if credential.is_file() and credential.stat().st_uid == os.getuid():
                token = credential.read_bytes().strip()
        if not token:
            raise RuntimeError("Desktop daemon credential unavailable")
        self.url = "http://" + address
        self.headers = {
            "Authorization": "Bearer " + token.decode(),
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-03-26",
            "X-Ait-Agent-Id": self.caller["id"],
        }
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        info = self.request("/v1/server/info")
        if info.get("server_id") != (self.data_dir / "server-id").read_text().strip():
            raise RuntimeError("Ait server identity does not match the selected data directory")
        self.version = info.get("version")

    def request(self, path, body=None):
        request = urllib.request.Request(self.url + path, headers=self.headers,
                                         data=None if body is None else json.dumps(body).encode())
        with self.opener.open(request, timeout=15) as response:
            return json.load(response)

    def call(self, name, arguments):
        response = self.request("/mcp/agents", {
            "jsonrpc": "2.0", "id": str(uuid.uuid4()), "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        })
        if "error" in response:
            raise RuntimeError(json.dumps(response["error"], ensure_ascii=False))
        result = response["result"]
        if result.get("isError"):
            raise RuntimeError(json.dumps(result, ensure_ascii=False))
        if "structuredContent" in result:
            return result["structuredContent"]
        for content in result.get("content", []):
            if content.get("type") == "text":
                return json.loads(content["text"])
        raise RuntimeError("Unexpected MCP response")

    def target(self, agent_id):
        result = self.call("get_agent_status", {"agentId": agent_id})
        snapshot = result["snapshot"]
        if snapshot.get("workspaceId") != self.caller.get("workspaceId") or not snapshot.get("workspaceId"):
            raise RuntimeError("Target must belong to the caller's workspace")
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path.home() / ".ait-server-desktop")
    parser.add_argument("--caller-id", help="Ait agent ID; otherwise match CODEX_SESSION_ID")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="List existing sessions in this workspace")
    for name in ("status", "activity", "send"):
        command = commands.add_parser(name)
        command.add_argument("agent_id")
        if name == "activity":
            command.add_argument("--limit", type=int, choices=range(1, 201), default=5)
        if name == "send":
            command.add_argument("--message-file", type=Path, required=True)
            command.add_argument("--message-id", default=None, help="Reuse to retry an ambiguous admission safely")
    args = parser.parse_args()
    client = AitClient(args.data_dir, args.caller_id)
    if args.command == "list":
        agents, cursor = [], None
        while True:
            page = client.call("list_agents", {"limit": 100, **({"cursor": cursor} if cursor else {})})
            agents.extend(a for a in page["agents"] if a.get("workspaceId") == client.caller["workspaceId"])
            cursor = page.get("nextCursor")
            if not cursor:
                break
        result = {"version": client.version, "caller": client.caller["id"], "agents": agents}
    else:
        result = client.target(args.agent_id)
        if args.command == "activity":
            result = client.call("get_agent_activity", {"agentId": args.agent_id, "limit": args.limit})
        elif args.command == "send":
            if args.agent_id == client.caller["id"]:
                raise RuntimeError("Refusing to send to this session itself")
            message = args.message_file.read_text().strip()
            if not message:
                raise RuntimeError("Message is empty")
            message_id = args.message_id or str(uuid.uuid4())
            print("message_id=" + message_id, file=sys.stderr)
            result = client.call("send_agent_prompt", {
                "agentId": args.agent_id,
                "prompt": "[Ait coordination from " + client.caller["id"] + "]\n" + message,
                "activeTurnBehavior": "steer", "messageId": message_id,
            })
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        print(f"ait coordination: {exc}", file=sys.stderr)
        sys.exit(1)
