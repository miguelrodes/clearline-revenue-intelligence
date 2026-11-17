#!/usr/bin/env python3
"""Private OpenAI tunnel; keep the existing local MCP bearer authentication."""
import argparse
import asyncio
import os
from pathlib import Path
import re
import signal
import subprocess
import sys

from dotenv import dotenv_values

from clearline.config import ROOT, Settings
from clearline.mcp_client import configuration, invoke

LOCAL_URL = "http://127.0.0.1:8003/mcp"
REHEARSAL_ENV_FILE = Path.home() / "Code/clearline-revenue-intelligence/.env"


def rehearsal_mcp_token(environ):
    """Read the already-configured token for the rehearsal server without printing it."""
    env_file = Path(environ.get("CLEARLINE_REHEARSAL_ENV_FILE", REHEARSAL_ENV_FILE))
    token = str(dotenv_values(env_file).get("CLEARLINE_MCP_TOKEN") or "").strip()
    if len(token) < 32:
        raise ValueError("The isolated rehearsal MCP token is not configured in its local environment file.")
    return token


def tunnel_client_path(environ):
    """Find the installed official client while allowing a local path override."""
    configured = environ.get("CLEARLINE_TUNNEL_CLIENT", "").strip()
    candidates = [Path(configured)] if configured else []
    candidates.extend((ROOT / "runtime/bin/tunnel-client", Path.home() / "Code/clearline-revenue-intelligence/runtime/bin/tunnel-client"))
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved.is_file() and os.access(resolved, os.X_OK):
            return resolved
    raise ValueError("The installed tunnel-client was not found. Set CLEARLINE_TUNNEL_CLIENT to its local path.")


def launch_configuration(mode, environ, url, token, client_path=None):
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
    executable = Path(client_path) if client_path else tunnel_client_path(environ)
    args = [str(executable), mode,
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


def redact_output(output, env, token):
    """Keep credentials out of diagnostic and long-running client output."""
    for secret in (env["CONTROL_PLANE_API_KEY"], env["CONTROL_PLANE_TUNNEL_ID"], token,
                   env["CLEARLINE_MCP_AUTHORIZATION"]):
        output = output.replace(secret, "[REDACTED]")
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("doctor", "run"), default="doctor", nargs="?")
    args = parser.parse_args()
    Settings.load()
    token = rehearsal_mcp_token(os.environ)
    os.environ["CLEARLINE_MCP_TOKEN"] = token
    os.environ["CLEARLINE_MCP_URL"] = LOCAL_URL
    _, url, _ = configuration()
    command, env = launch_configuration(args.mode, os.environ, url, token)
    status = asyncio.run(invoke("get_agent_status", {}))
    if not status["health"].get("disposable_demo"):
        raise ValueError("The running backend must use its registered disposable demo session")
    print("Private tunnel to the authenticated demo MCP endpoint. No public listener. Ctrl+C stops it.", flush=True)
    if args.mode == "doctor":
        result = subprocess.run(command, env=env, text=True, capture_output=True, timeout=60)
        print(redact_output(result.stdout + result.stderr, env, token))
        return result.returncode
    process = subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, bufsize=1)
    try:
        for line in process.stdout:
            print(redact_output(line, env, token), end="", flush=True)
        return process.wait()
    except KeyboardInterrupt:
        process.send_signal(signal.SIGINT)
        return process.wait()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        sys.exit(str(exc))
