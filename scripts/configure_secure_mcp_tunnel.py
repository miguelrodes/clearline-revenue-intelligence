#!/usr/bin/env python3
"""Save Secure MCP Tunnel credentials locally without echoing them."""
import getpass
import re
from pathlib import Path

from dotenv import set_key

ROOT = Path(__file__).resolve().parents[1]


def configure():
    tunnel_id = getpass.getpass("CONTROL_PLANE_TUNNEL_ID (hidden): ").strip()
    if not re.fullmatch(r"tunnel_[A-Za-z0-9_-]+", tunnel_id):
        raise ValueError("The tunnel ID format is invalid. No value was saved.")

    api_key = getpass.getpass("CONTROL_PLANE_API_KEY (hidden): ").strip()
    if not api_key or any(character in api_key for character in "\r\n"):
        raise ValueError("The runtime API key is empty or invalid. No value was saved.")

    target = ROOT / ".env"
    target.touch(mode=0o600, exist_ok=True)
    set_key(str(target), "CONTROL_PLANE_TUNNEL_ID", tunnel_id, quote_mode="always")
    set_key(str(target), "CONTROL_PLANE_API_KEY", api_key, quote_mode="always")
    target.chmod(0o600)
    print("Tunnel credentials saved in the ignored local .env file with owner-only permissions.")


if __name__ == "__main__":
    try:
        configure()
    except (OSError, ValueError) as error:
        raise SystemExit(str(error))
