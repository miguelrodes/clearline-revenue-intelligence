#!/usr/bin/env python3
"""Private OpenAI tunnel; keep the existing local MCP bearer authentication."""
import argparse
import asyncio
import os
from pathlib import Path
import re
import subprocess
import sys

from clearline.config import ROOT
from clearline.mcp_client import configuration, invoke

LOCAL_URL = "http://127.0.0.1:8000/mcp"


def launch_configuration(mode, environ, url, token):
    """Do not inherit alternate endpoints, raw logging, profiles or API-key fallback."""
    if mode not in ("doctor", "run"):
        raise ValueError("Choose doctor or run")
    if url != LOCAL_URL:
        raise ValueError("CLEARLINE_MCP_URL must be " + LOCAL_URL)
    tunnel_id = environ.get("CONTROL_PLANE_TUNNEL_ID", "").strip()
    key = environ.get("CONTROL_PLANE_API_KEY", "").strip()
    if not re.fullmatch(r"tunnel_[A-Za-z0-9_-]+", tunnel_id) or not key:
        raise ValueError("Set CONTROL_PLANE_TUNNEL_ID and CONTROL_PLANE_API_KEY locally in .env. Never paste keys into chat.")
    if len(token) < 32 or any(c in token + key for c in "\r\n"):
        raise ValueError("Invalid MCP or runtime credential")
    env = {k: environ[k] for k in ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "SSL_CERT_FILE", "SSL_CERT_DIR") if k in environ}
    env.update(CONTROL_PLANE_TUNNEL_ID=tunnel_id, CONTROL_PLANE_API_KEY=key,
               CLEARLINE_MCP_AUTHORIZATION="Bearer " + token)
    args = [str(ROOT / "runtime/bin/tunnel-client"), mode,
            "--control-plane.base-url", "https://api.openai.com",
            "--control-plane.api-key", "env:CONTROL_PLANE_API_KEY",
            "--mcp.server-url", LOCAL_URL,
            "--mcp.extra-headers", "Authorization: env:CLEARLINE_MCP_AUTHORIZATION",
            "--mcp.discovery-extra-headers", "Authorization: env:CLEARLINE_MCP_AUTHORIZATION",
            "--health.listen-addr", "127.0.0.1:8080",
            "--log.http-raw-unsafe=false", "--allow-remote-ui=false"]
    if mode == "doctor":
        args.append("--explain")
    return args, env


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("doctor", "run"), default="doctor", nargs="?")
    args = parser.parse_args()
    _, url, token = configuration()
    command, env = launch_configuration(args.mode, os.environ, url, token)
    if not Path(command[0]).is_file():
        raise ValueError("Install the official tunnel-client in runtime/bin first; see docs/mcp-integration.md")
    status = asyncio.run(invoke("get_agent_status", {}))
    if not status["health"].get("disposable_demo"):
        raise ValueError("The running backend must use its registered disposable demo session")
    print("Private tunnel to the authenticated demo MCP endpoint. No public listener. Ctrl+C stops it.", flush=True)
    if args.mode == "doctor":
        result = subprocess.run(command, env=env, text=True, capture_output=True, timeout=60)
        output = (result.stdout + result.stderr).replace(env["CONTROL_PLANE_API_KEY"], "[REDACTED]").replace(token, "[REDACTED]")
        print(output)
        return result.returncode
    os.execve(command[0], command, env)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        sys.exit(str(exc))
