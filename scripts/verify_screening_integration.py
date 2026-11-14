"""Read-only runtime acceptance plus an unchanged-assessment cache check."""
import argparse,json,os,sys,time
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from dotenv import load_dotenv
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from clearline.store import Store
from clearline.screening_budget import summary as budget

p=argparse.ArgumentParser();p.add_argument('--env-file',type=Path,required=True);p.add_argument('--api',default='http://127.0.0.1:8002');p.add_argument('--frontend',default='http://127.0.0.1:3001');args=p.parse_args();load_dotenv(args.env_file)
out={};store=Store(Path(__file__).resolve().parents[1]/'runtime/phase3/screening.sqlite3');before=budget(store);jobs=store.rows('SELECT COUNT(*) n FROM jobs')[0]['n']
def req(base,path,body=None,headers=None):
 start=time.monotonic()
 r=urlopen(Request(base+path,data=json.dumps(body).encode() if body is not None else None,headers=headers or {'Content-Type':'application/json','X-Clearline-Client':'web','Origin':args.frontend}),timeout=30)
 value=json.load(r);out[base+path]={'status':r.status,'seconds':round(time.monotonic()-start,3)};return value
s=req(args.api,'/api/screening');assert s['source_records']==2600 and sum(s['classifications'].values())==2600
assert req(args.frontend,'/api/features')['prospect_screening'] is True
assert req(args.frontend,'/api/screening')['assessed']==s['assessed']
first=req(args.api,'/api/screening/agencies?classification=unverified_prospect&limit=10')['items'][0]
d=req(args.api,'/api/screening/agencies/'+first['id']);assert d['qualification_current'] and d['outreach_prerequisites']
for _ in range(2):assert req(args.api,'/api/screening/agencies/'+first['id']+'/qualify',{'evidence_hash':first['evidence_hash']})['reused']
try:req(args.api,'/mcp',{})
except HTTPError as e:assert e.code==401;out['mcp_unauthenticated']=401
headers={'Authorization':'Bearer '+os.environ['CLEARLINE_MCP_TOKEN'],'Content-Type':'application/json','Accept':'application/json, text/event-stream'}
tools=req(args.api,'/mcp',{'jsonrpc':'2.0','id':1,'method':'tools/list'},headers)['result']['tools'];names={t['name'] for t in tools}
assert {'get_prospect_screening','get_screened_agency','decide_screened_agency','record_agency_information','prepare_agency_outreach','record_agency_activity','review_outreach','decide_outreach'}<=names
mcp=req(args.api,'/mcp',{'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'get_prospect_screening','arguments':{}}},headers)['result'];assert not mcp.get('isError') and mcp['structuredContent']['data']['assessed']==s['assessed']
assert budget(store)==before and store.rows('SELECT COUNT(*) n FROM jobs')[0]['n']==jobs
out.update(mcp_tools=len(tools),next_fastapi_mcp_same_state=True,unchanged_assessment_reused_without_new_jobs_or_cost=True,summary=s)
(store.path.parent/'http-integration.json').write_text(json.dumps(out,indent=2));print(json.dumps(out,indent=2))
