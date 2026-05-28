"""Charge .env : SEARCH_TERMS, USE_CASE, MCP_URL."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"

HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}


@dataclass(frozen=True)
class Env:
    search_terms: tuple[str, ...]
    use_case: str
    mcp_url: str

    @classmethod
    def load(cls, path: Path = ENV_FILE) -> Env:
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                os.environ[k.strip()] = v.strip().strip("'\"")
        parts = os.environ.get("SEARCH_TERMS", "").split("|") if "|" in os.environ.get("SEARCH_TERMS", "") else os.environ.get("SEARCH_TERMS", "").splitlines()
        return cls(
            search_terms=tuple(p.strip() for p in parts if p.strip()),
            use_case=os.environ.get("USE_CASE", "").strip(),
            mcp_url=os.environ.get("MCP_URL", "https://mcp.data.gouv.fr/mcp"),
        )

    @property
    def primary_term(self) -> str:
        if not self.search_terms:
            raise ValueError("SEARCH_TERMS vide dans .env")
        return self.search_terms[0]


class Mcp:
    def __init__(self, env: Env) -> None:
        self.env = env

    def call(self, method: str, params: dict | None = None, req_id: str = "1") -> str:
        body = json.dumps(
            {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}}
        ).encode()
        req = urllib.request.Request(self.env.mcp_url, data=body, headers=HEADERS, method="POST")
        with urllib.request.urlopen(req, timeout=120) as resp:
            return self._text(resp.read().decode())

    def tool(self, name: str, arguments: dict, req_id: str = "1") -> str:
        return self.call("tools/call", {"name": name, "arguments": arguments}, req_id)

    @staticmethod
    def _text(raw: str) -> str:
        for line in raw.splitlines():
            if not line.startswith("data: "):
                continue
            payload = json.loads(line[6:])
            if "error" in payload:
                raise RuntimeError(payload["error"])
            result = payload.get("result", {})
            for block in result.get("content") or []:
                if block.get("type") == "text":
                    return block["text"]
            if result:
                return json.dumps(result, ensure_ascii=False, indent=2)
        return raw
