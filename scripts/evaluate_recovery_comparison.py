"""Independent blind comparison of saved current-engine results; no portfolio mutations or messages."""
import asyncio,json,random,time,sys
from dataclasses import replace
from pydantic import BaseModel,ConfigDict,Field
from agents import Agent,Runner,ModelSettings,RunConfig,OpenAIResponsesModel
from openai.types.shared import Reasoning
from clearline.config import Settings,ROOT
from clearline.store import Store
from clearline.evidence import ENGINE_VERSION,current_assessment
from clearline.operations import latest_assessment
from clearline.telemetry import client_for
out=ROOT/'runtime/overhaul';store=Store(out/'sample.sqlite3');settings=replace(Settings.load(),model='gpt-6-astra',timeout_seconds=180)
samples=json.loads((out/'sample_before.json').read_text());latest={}
evidence_store=Store(out/'portfolio.sqlite3')
for row in samples:
 a=latest_assessment(evidence_store,row['id'])
 with evidence_store.connect() as con:current=current_assessment(con,row['id'],a)
 if current:latest[row['id']]={'after':a}
class Score(BaseModel):
 model_config=ConfigDict(extra='forbid')
 evidence_coverage:int=Field(ge=1,le=5)
 specificity:int=Field(ge=1,le=5)
 personalization:int=Field(ge=1,le=5)
 action_appropriateness:int=Field(ge=1,le=5)
 uncertainty:int=Field(ge=1,le=5)
 sales_progress:int=Field(ge=1,le=5)
 factuality:int=Field(ge=1,le=5)
class Comparison(BaseModel):
 model_config=ConfigDict(extra='forbid')
 A:Score
 B:Score
 preferred:str
 reason:str
 important_issues:list[str]
sem=asyncio.Semaphore(4)
async def one(r):
 async with sem:
  old=r['before'];new=latest[r['id']]['after'];fields=['decision','strategy','rationale','recommended_action','subject','body','verification_tasks','alternatives']
  old={k:old.get(k) for k in fields};new={k:new.get(k) for k in fields}
  if r['drafts']:old['body']=r['drafts'][-1]['body'];old['subject']=r['drafts'][-1]['subject']
  swapped=int(r['id'][0],16)%2==0;A,B=(new,old) if swapped else (old,new)
  jid=store.enqueue('evaluation',{},r['id'],'blind-final:'+ENGINE_VERSION+':'+r['id'])
  job={'id':jid,'opportunity_id':r['id']}
  decision_job=evidence_store.rows("SELECT job_id FROM events WHERE opportunity_id=? AND kind='agent_decision' AND json_extract(details,'$.engine_version')=? ORDER BY id DESC LIMIT 1",(r['id'],ENGINE_VERSION))[0]['job_id']
  retrieved={}
  for row in evidence_store.rows("SELECT details FROM events WHERE job_id=? AND kind='evidence_retrieved' ORDER BY id",(decision_job,)):
   record=json.loads(row['details']);value=record['evidence']
   if record['section'].startswith('previous:'):
    for previous in value.get('assessments',[]):
     previous['details']={k:v for k,v in previous['details'].items() if k in fields}
   retrieved[record['section']]=value
  prompt={'retrieved_evidence':retrieved,'source_account':r['evidence'],'source_orders':r['source_orders'],'messages':r['messages'],'A':A,'B':B}
  instructions='''Blindly compare two customer recovery proposals against source evidence. Score each 1-5 on evidence coverage, commercial specificity, personalization, appropriateness, uncertainty, sales progression, factuality. Prefer a useful evidence-grounded next step, not verbosity. The system is fictional/simulated. Historical revenue decline is not recoverable revenue. CRM notes are undated; never assume current need or expose internal notes in customer email. Distributor sell-through data is unavailable; requiring it is a flaw. Identity conflicts block customer outreach, but operational/channel warnings allow neutral reviewed support/clarification. No-action can be excellent for stable accounts or recently contacted accounts. Exact human approval remains mandatory. Penalize invented claims, commitments, contact identities, quantities, stale/redundant questions, generic stock questions when a more specific training/support/contact need exists. New fields or more words do not imply quality. Assess customer-facing text and the actual proposed next step. Missing detail vs fabrication are different. Return preferred A/B/tie and specific defects. Do not infer which system is newer.'''
  store.event('evaluation_input',{'engine':ENGINE_VERSION,'context_hash':latest[r['id']]['after']['context_hash'],'prompt':prompt},jid,r['id'])
  try:
   async with client_for(store,job,settings) as client:
    agent=Agent(name='Blind independent commercial evaluator',instructions=instructions,output_type=Comparison,model=OpenAIResponsesModel(model=settings.model,openai_client=client),model_settings=ModelSettings(reasoning=Reasoning(effort='high'),store=False,max_tokens=6000))
    x=await Runner.run(agent,json.dumps(prompt),max_turns=1,run_config=RunConfig(tracing_disabled=True))
   result={'id':r['id'],'name':r['name'],'engine':ENGINE_VERSION,'context_hash':latest[r['id']]['after']['context_hash'],'new_is':'A' if swapped else 'B','comparison':x.final_output.model_dump()}
  except Exception as ex:result={'id':r['id'],'failure':type(ex).__name__,'detail':str(ex)}
  print(json.dumps({k:v for k,v in result.items() if k!='comparison'}|({'preferred':result['comparison']['preferred']} if 'comparison' in result else {})),flush=True)
  with (out/('blind_evaluation_'+ENGINE_VERSION+'.jsonl')).open('a') as f:f.write(json.dumps(result)+'\n')
async def main():await asyncio.gather(*(one(r) for r in samples if r['id'] in latest and (len(sys.argv)==1 or r['id'] in sys.argv[1:])))
asyncio.run(main())
