"""Plugin packaging: the manifest, the MCP config and the tool annotations the directory checks."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_mcp_config_uses_declared_user_config_and_a_locked_run():
    manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
    server = json.loads((ROOT / ".mcp.json").read_text())["mcpServers"]["alphaosint-prospector"]
    assert "--locked" in server["args"]
    refs = set(re.findall(r"\$\{user_config\.(\w+)\}", json.dumps(server)))
    assert refs and refs <= set(manifest["userConfig"])
    assert manifest["userConfig"]["apify_token"]["sensitive"] is True


def test_every_tool_has_a_title_and_annotations():
    from alpha_prospector.mcp_server import mcp

    tools = asyncio.run(mcp.list_tools())
    assert len(tools) == 14
    for tool in tools:
        assert tool.title and tool.annotations is not None, tool.name
        assert tool.annotations.read_only_hint is not None, tool.name
    by_name = {t.name: t.annotations for t in tools}
    assert by_name["list_leads"].read_only_hint is True
    assert by_name["find_emails"].open_world_hint is True
    assert by_name["set_icp"].destructive_hint is True


def test_no_affiliate_codes_ship_in_the_plugin():
    for path in ROOT.rglob("*"):
        if path.is_file() and path.suffix in {".md", ".py", ".json"} and not {".venv", ".git", "tests"} & set(path.parts):
            assert "fpr=" not in path.read_text(errors="ignore"), path
