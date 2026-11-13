"""Read and idempotence checks against the isolated review server only."""
import json,os,time,sys
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from dotenv import load_dotenv
load_dotenv(Path('/Users/miguelrodes/Code/clearline-revenue-intelligence/.env'))
BASE='http://127.0.0.1:8001';out={}
def req(path,body=None,headers=None):
    start=time.monotonic()
    r=urlopen(Request(BASE+path,data=json.dumps(body).encode() if body is not None else None,headers=headers or {'Content-Type':'application/json','X-Clearline-Client':'web','Origin':'http://127.0.0.1:3001'}),timeout=30)
    value=json.load(r);out[path]={'status':r.status,'seconds':round(time.monotonic()-start,3)};return value
s=req('/api/screening');assert s['source_records']==2600 and sum(s['classifications'].values())==2600
listing=req('/api/screening/agencies?outcome=qualified&limit=10');assert listing['total']>=1
first=listing['items'][0];detail=req('/api/screening/agencies/'+first['id']);assert detail['qualification']['review_passed'] and not detail['qualification']['outreach_eligible']
a=req('/api/screening/agencies/'+first['id']+'/qualify',{'evidence_hash':first['evidence_hash']});b=req('/api/screening/agencies/'+first['id']+'/qualify',{'evidence_hash':first['evidence_hash']});assert a==b
rejected=req('/api/screening/agencies?outcome=reject&limit=10');assert rejected['total']>=1
for x in rejected['items']:assert req('/api/screening/agencies/'+x['id'])['qualification']['decision']['outcome']=='reject'
assert req('/api/features')['prospect_screening']
try:req('/mcp',{})
except HTTPError as e:assert e.code==401;out['mcp_unauthenticated']=401
headers={'Authorization':'Bearer '+os.environ['CLEARLINE_MCP_TOKEN'],'Content-Type':'application/json','Accept':'application/json, text/event-stream','MCP-Protocol-Version':'2025-11-25'}
tools=req('/mcp',{'jsonrpc':'2.0','id':1,'method':'tools/list'},headers)['result']['tools'];assert len(tools)==42
mcp=req('/mcp',{'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'get_prospect_screening','arguments':{}}},headers)['result'];assert not mcp.get('isError');assert mcp['structuredContent']['data']['source_records']==2600
out['mcp_tools']=len(tools);out['approved_or_sent']=False;out['summary']=s;out['examples']={'qualified':first['name'],'rejected':[x['name'] for x in rejected['items']]}
Path('runtime/phase3/http-mcp-verification.json').write_text(json.dumps(out,indent=2));print(json.dumps(out,indent=2))
