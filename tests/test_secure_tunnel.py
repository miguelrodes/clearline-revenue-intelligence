"""The tunnel launcher must preserve the private endpoint and secret boundaries."""
import importlib.util
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location("secure_tunnel", Path(__file__).resolve().parents[1] / "scripts/start_secure_mcp_tunnel.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_tunnel_uses_secret_references_and_discards_ambient_overrides():
    env = {"HOME": "/tmp", "CONTROL_PLANE_TUNNEL_ID": "tunnel_test", "CONTROL_PLANE_API_KEY": "private-runtime-key", "OPENAI_API_KEY": "model-key", "CONTROL_PLANE_BASE_URL": "https://unexpected.invalid", "MCP_SERVER_URL": "https://unexpected.invalid", "LOG_HTTP_RAW_UNSAFE": "true", "ALLOW_REMOTE_UI": "true", "TUNNEL_CLIENT_CONFIG": "/tmp/unexpected.yaml"}
    token = "private-mcp-token-" * 4
    args, child = module.launch_configuration("doctor", env, module.LOCAL_URL, token)
    assert token not in " ".join(args) and env["CONTROL_PLANE_API_KEY"] not in " ".join(args)
    assert child["CLEARLINE_MCP_AUTHORIZATION"] == "Bearer " + token
    assert child["CONTROL_PLANE_API_KEY"] == env["CONTROL_PLANE_API_KEY"]
    assert set(child) == {"HOME", "CONTROL_PLANE_TUNNEL_ID", "CONTROL_PLANE_API_KEY", "CLEARLINE_MCP_AUTHORIZATION"}
    assert "https://api.openai.com" in args and module.LOCAL_URL in args
    assert "--log.http-raw-unsafe=false" in args and "--allow-remote-ui=false" in args
    assert args.count("Authorization: env:CLEARLINE_MCP_AUTHORIZATION") == 2


@pytest.mark.parametrize("env", [{}, {"CONTROL_PLANE_TUNNEL_ID": "tunnel_test", "OPENAI_API_KEY": "model-key"}, {"CONTROL_PLANE_TUNNEL_ID": "bad", "CONTROL_PLANE_API_KEY": "key"}])
def test_tunnel_requires_its_own_runtime_credentials(env):
    with pytest.raises(ValueError, match="CONTROL_PLANE"):
        module.launch_configuration("run", env, module.LOCAL_URL, "x" * 48)


def test_tunnel_refuses_remote_or_non_mcp_targets():
    with pytest.raises(ValueError, match="CLEARLINE_MCP_URL"):
        module.launch_configuration("run", {}, "http://127.0.0.1:8000/api/overview", "x" * 48)
