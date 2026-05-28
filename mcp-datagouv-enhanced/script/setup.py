#!/usr/bin/env python3
"""Init MCP + recherches test (1 page)."""

from script.env import Env, Mcp


class Setup:
    def __init__(self) -> None:
        self.cfg = Env.load()
        self.mcp = Mcp(self.cfg)

    def run(self) -> None:
        q = self.cfg.primary_term
        print(f"Query: {q}\n→ initialize\n", self.mcp.call("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "setup", "version": "1.0"},
        }, "1")[:180])

        for name, args, rid in [
            ("search_datasets", {"query": q, "page": 1, "page_size": 5}, "2"),
            ("search_organizations", {"query": q, "page": 1, "page_size": 3}, "3"),
            ("search_dataservices", {"query": q, "page": 1, "page_size": 3}, "4"),
            ("get_metrics", {"dataset_id": "65df34eeb2a9d54adad981d7"}, "5"),
        ]:
            print(f"\n→ {name}\n", self.mcp.tool(name, args, rid))


if __name__ == "__main__":
    Setup().run()
