"""Bounded real Phase 3 exercise with predeclared strata and fresh-context evaluation."""
import argparse,asyncio,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from screening_dev import configuration
from clearline.store import Store
from clearline.screening import screen,queue,detail,summary
from clearline.worker import execute_job,Capacity,worker_lock
from clearline.screening_agent import Strict
from clearline.telemetry import client_for
from pydantic import Field

class IndependentEvaluation(Strict):
    factuality:int=Field(ge=1,le=5)
    commercial_relevance:int=Field(ge=1,le=5)
    identity_channel:int=Field(ge=1,le=5)
    next_step_quality:int=Field(ge=1,le=5)
    uncertainty:int=Field(ge=1,le=5)
    critical_issues:list[str]
    justification:str

async def evaluate(store,settings,cases,start_event):
    from agents import Agent,Runner,ModelSettings,RunConfig,OpenAIResponsesModel
    from openai.types.shared import Reasoning
    semaphore=asyncio.Semaphore(3);capacity=Capacity(settings)
    def cost():return sum(json.loads(x['details']).get('cost_usd') or 0 for x in store.rows("SELECT details FROM events WHERE kind='api_response' AND id>?",(start_event,)))
    async def one(case):
        async with semaphore:
            if cost()>8:raise RuntimeError('Evaluation budget reached; stop and inspect saved results')
            row=detail(store,case['id']);queued=queue(store,settings,row['id'],row['evidence_hash'])
            with store.connect(write=True) as con:
                con.execute("UPDATE jobs SET status='running',attempts=attempts+1,started_at=datetime('now') WHERE id=? AND status='queued'",(queued['job_id'],))
            j=store.rows('SELECT * FROM jobs WHERE id=?',(queued['job_id'],))[0];j['payload']=json.loads(j['payload'])
            if j['status']=='running':await execute_job(store,settings,j,capacity=capacity)
            row=detail(store,case['id']);result=row['qualification']
            if not result:return dict(case,error=row['jobs'])
            # The evaluator does not see expected outcomes or the operational supervisor verdict.
            async with client_for(store,j,settings) as client:
                reviewer=Agent(name='Independent Phase 3 audit',instructions='Independently score the qualification against original fictional source evidence. No web facts. Qualified means priority for internal discovery only, never demand or permission. Reject inflated fit, clinical-testing assumptions, invented facts, channel bypass, false net-new certainty and pointless work. Scores 1-5: 1 unusable, 3 defensible but weak, 4 strong, 5 excellent. Report every critical error. An existing-customer rejection is valid only from the new-prospect shortlist, not all account work.',model=OpenAIResponsesModel(model=settings.model,openai_client=client),model_settings=ModelSettings(reasoning=Reasoning(effort='high'),max_tokens=2500,store=False),output_type=IndependentEvaluation)
                response=await Runner.run(reviewer,json.dumps({'task_context':'Clearline fictional agency screening; internal discovery only','screening_record':{k:row[k] for k in ('id','name','state','classification','evidence_hash')},'original_evidence':row['evidence'],'actual_evidence_tool_history':[json.loads(x['details']) for x in store.rows("SELECT details FROM events WHERE job_id=? AND kind='screening_evidence_read' ORDER BY id",(j['id'],))],'candidate_decision':result['decision']}),max_turns=2,run_config=RunConfig(tracing_disabled=True));audit=response.final_output.model_dump()
            output=dict(case,name=row['name'],classification=row['classification'],decision=result['decision'],operational_review_passed=result['review_passed'],expected_agreement=result['decision']['outcome'] in case['expected'],independent=audit)
            Path('runtime/phase3/evaluations/'+row['id']+'.json').write_text(json.dumps(output,indent=2));print(row['name'],result['decision']['outcome'],'agreement',output['expected_agreement'],flush=True)
            return output
    results=await asyncio.gather(*(one(c) for c in cases));usage=[json.loads(x['details']) for x in store.rows("SELECT details FROM events WHERE kind='api_response' AND id>?",(start_event,))]
    report={'cases':results,'summary':summary(store),'usage':{'responses':len(usage),'input_tokens':sum(x.get('input_tokens',0) for x in usage),'output_tokens':sum(x.get('output_tokens',0) for x in usage),'estimated_usd':cost(),'unpriced':sum(x.get('cost_usd') is None for x in usage)},'independence':'Fresh-context evaluator does not see expectations or original review; same configured model family, not blinded human evaluation.'}
    Path('runtime/phase3/evaluation.json').write_text(json.dumps(report,indent=2));print(json.dumps(report['usage']),flush=True)

def main():
    p=argparse.ArgumentParser();p.add_argument('--env-file',type=Path,required=True);args=p.parse_args();settings=configuration(args.env_file,True);store=Store(settings.db_path);screen(store,settings)
    path=Path('runtime/phase3/evaluations');path.mkdir(parents=True,exist_ok=True)
    manifest=Path('runtime/phase3/evaluation-manifest.json')
    if manifest.exists():cases=json.loads(manifest.read_text())
    else:
        strata=[('unverified_prospect','county_jail',3,['qualified']),('unverified_prospect','state_prison',2,['qualified']),('unverified_prospect','police_dept',2,['qualified','investigate']),('unverified_prospect','sheriff',1,['qualified','investigate']),('unverified_prospect','probation_parole',1,['reject','defer','investigate']),('unverified_prospect','drug_court',1,['reject','defer','investigate']),('verified_existing','',2,['reject']),('possible_existing_channel','',2,['human_verification','investigate','defer','reject']),('ambiguous_identity','',2,['human_verification','investigate','defer','reject'])]
        cases=[]
        for category,typ,count,expected in strata:
            rows=store.rows("SELECT id FROM agency_screenings WHERE active=1 AND classification=? AND (?='' OR agency_type=?) ORDER BY id LIMIT ?",(category,typ,typ,count))
            cases.extend(dict(id=x['id'],stratum=category+':'+typ,expected=expected) for x in rows)
        manifest.write_text(json.dumps(cases,indent=2))
    start=store.rows('SELECT COALESCE(MAX(id),0) n FROM events')[0]['n']
    Path('runtime/phase3/evaluation-start.json').write_text(json.dumps({'event_id':start}))
    with worker_lock(settings.db_path):asyncio.run(evaluate(store,settings,cases,start))
if __name__=='__main__':main()
