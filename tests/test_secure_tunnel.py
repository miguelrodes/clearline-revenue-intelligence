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
    args, child = module.launch_configuration("doctor", env, module.LOCAL_URL, token, client_path="/tmp/tunnel-client")
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


def test_tunnel_refuses_remote_or_main_preview_targets():
    with pytest.raises(ValueError, match="CLEARLINE_MCP_URL"):
        module.launch_configuration("run", {}, "http://127.0.0.1:8000/api/overview", "x" * 48)
    with pytest.raises(ValueError, match="CLEARLINE_MCP_URL"):
        module.launch_configuration("run", {}, "http://127.0.0.1:8000/mcp", "x" * 48)


def test_tunnel_client_output_redacts_all_credentials():
    env = {"CONTROL_PLANE_API_KEY": "runtime-secret", "CONTROL_PLANE_TUNNEL_ID": "tunnel_private",
           "CLEARLINE_MCP_AUTHORIZATION": "Bearer mcp-secret"}
    output = module.redact_output("runtime-secret tunnel_private Bearer mcp-secret", env, "mcp-secret")
    assert "runtime-secret" not in output
    assert "tunnel_private" not in output
    assert "mcp-secret" not in output


def test_tunnel_client_uses_existing_installed_path(monkeypatch, tmp_path):
    installed = tmp_path / "tunnel-client"
    installed.write_text("client")
    installed.chmod(0o700)
    monkeypatch.setattr(module, "ROOT", tmp_path / "integration")
    monkeypatch.setattr(module.Path, "home", lambda: tmp_path)
    code_client = tmp_path / "Code/clearline-revenue-intelligence/runtime/bin/tunnel-client"
    code_client.parent.mkdir(parents=True)
    code_client.write_text("client")
    code_client.chmod(0o700)
    assert module.tunnel_client_path({}) == code_client
    assert module.tunnel_client_path({"CLEARLINE_TUNNEL_CLIENT": str(installed)}) == installed


def test_credential_setup_prompts_without_echoing_values(monkeypatch, tmp_path, capsys):
    spec = importlib.util.spec_from_file_location("secure_tunnel_setup", Path(__file__).resolve().parents[1] / "scripts/configure_secure_mcp_tunnel.py")
    setup = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(setup)
    values = iter(("tunnel_rehearsal", "restricted-private-key"))
    monkeypatch.setattr(setup, "ROOT", tmp_path)
    monkeypatch.setattr(setup.getpass, "getpass", lambda _: next(values))

    setup.configure()

    target = tmp_path / ".env"
    assert target.stat().st_mode & 0o777 == 0o600
    contents = target.read_text()
    assert "CONTROL_PLANE_TUNNEL_ID" in contents
    assert "CONTROL_PLANE_API_KEY" in contents
    assert "restricted-private-key" not in capsys.readouterr().out
