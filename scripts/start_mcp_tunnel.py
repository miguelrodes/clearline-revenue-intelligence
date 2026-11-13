#!/usr/bin/env python3
"""Checked, MCP-only tunnel for authenticated clients. ChatGPT requires separate OAuth/tunnel setup."""
import asyncio,json,subprocess,sys
from pathlib import Path
from clearline.mcp_client import invoke,configuration
from clearline.config import ROOT

def main():
    _,url,_=configuration()
    if url not in ('http://127.0.0.1:8000/mcp','http://localhost:8000/mcp'):raise ValueError('Start the tunnel against the local demo endpoint, not an existing remote URL')
    status=asyncio.run(invoke('get_agent_status',{}))
    if not status['health'].get('disposable_demo'):raise ValueError('The running backend must use its registered disposable demo session')
    command=['ngrok','http','8000','--host-header=localhost','--inspect=false','--traffic-policy-file',str(ROOT/'scripts/ngrok-mcp-policy.yml')]
    print('Only /mcp is exposed; every MCP request requires CLEARLINE_MCP_TOKEN. Ctrl+C closes the tunnel.')
    print('Do not connect ChatGPT with No authentication. This bearer-token setup is for authenticated MCP clients.')
    raise SystemExit(subprocess.call(command))

if __name__=='__main__':
    try:main()
    except ValueError as e:sys.exit(str(e))
