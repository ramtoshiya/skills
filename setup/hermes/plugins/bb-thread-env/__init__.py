"""Export the session's bb thread id as BB_THREAD_ID and unset the other per-thread names.

The id comes from Hermes's undocumented gateway state (`gateway.run_api._ACTIVE_RUNNER`
and each authority's `_local_editor_mcp`), so a Hermes update can break it. `docs/setup.md`
describes the symptom.
"""

from __future__ import annotations

from typing import Optional

BRIDGE_SERVER = "bb-bridge"
THREAD_ID_ENV = "BB_ACP_DYNAMIC_TOOL_THREAD_ID"
EXPORTED = ("BB_THREAD_ID", "BB_PROJECT_ID", "BB_ENVIRONMENT_ID", "BB_THREAD_STORAGE")


def bridge_thread_id(servers: list[dict]) -> Optional[str]:
    """The thread id in the env of the `bb-bridge` entry of an ACP MCP server list."""
    for server in servers:
        if server.get("name") != BRIDGE_SERVER:
            continue
        for entry in server.get("env") or ():
            if entry.get("name") == THREAD_ID_ENV and entry.get("value"):
                return str(entry["value"])
    return None


def session_thread_id(session_id: str) -> Optional[str]:
    """The bb thread of a gateway session, read where the session's turns read their MCP servers."""
    from gateway.run_api import _ACTIVE_RUNNER
    from gateway.session_authorities import all_authorities
    from gateway.session_local_mcp import session_scope

    if _ACTIVE_RUNNER is None:
        return None
    for authority in all_authorities(_ACTIVE_RUNNER):
        servers = getattr(authority, "_local_editor_mcp", {}).get(session_scope(authority, session_id))
        if servers:
            return bridge_thread_id(servers)
    return None


def resolve(session_id: str) -> dict[str, Optional[str]]:
    values: dict[str, Optional[str]] = dict.fromkeys(EXPORTED)
    values["BB_THREAD_ID"] = session_thread_id(session_id)
    return values


def register(ctx) -> None:
    ctx.register_session_env(EXPORTED, resolve)
