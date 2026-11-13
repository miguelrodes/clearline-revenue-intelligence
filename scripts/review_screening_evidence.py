"""Recheck incomplete audit packets against the actual evidence-tool history.
Original reviews remain untouched. No qualification or sales records are changed.
"""
import asyncio,json,sys,argparse
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from screening_dev import configuration
from evaluate_screening import IndependentEvaluation
from clearline.store import Store
from clearline.screening import detail
from clearline.telemetry import client_for

async def run(settings):
    from agents import Agent,Runner,ModelSettings,RunConfig,OpenAIResponsesModel
    from openai.types.shared import Reasoning
    store=Store(settings.db_path);report_path=Path('runtime/phase3/complete-evidence-audit.json');results=json.loads(report_path.read_text()) if report_path.exists() else []
    checked={x['id'] for x in results}
    for path in sorted(Path('runtime/phase3/evaluations').glob('*.json')):
        old=json.loads(path.read_text())
        if not old['independent']['critical_issues'] or old['id'] in checked:continue
        row=detail(store,old['id']);job=store.rows('SELECT * FROM jobs WHERE id=(SELECT job_id FROM agency_qualifications WHERE agency_id=? AND evidence_hash=? ORDER BY created_at DESC,rowid DESC LIMIT 1)',(row['id'],row['evidence_hash']))[0]
        evidence=[json.loads(x['details']) for x in store.rows("SELECT details FROM events WHERE job_id=? AND kind='screening_evidence_read' ORDER BY id",(job['id'],))]
        packet={'task_context':'Clearline fictional public-agency prospect screening. Qualified means priority for a bounded internal discovery task, never validated need or authorization.','screening_record':{k:row[k] for k in ('id','name','state','classification','evidence_hash')},'source_evidence':row['evidence'],'actual_evidence_tool_history':evidence,'candidate_decision':row['qualification']['decision']}
        async with client_for(store,job,settings) as client:
            reviewer=Agent(name='Independent complete-evidence audit',instructions='Independently score this decision against original evidence and the recorded tool outputs. No original reviewer verdict or expected answer is provided. Scores 1-5: 1 unusable, 3 weak but defensible, 4 strong, 5 excellent. Report blocking factual, channel, suitability or authorization errors. Actual retrieval pagination is distinct from exhaustive knowledge of the business; unidentified distributor sales remain unknown. Qualified is internal discovery only; existing buyers should leave only the prospect shortlist.',model=OpenAIResponsesModel(model=settings.model,openai_client=client),model_settings=ModelSettings(reasoning=Reasoning(effort='high'),max_tokens=2500,store=False),output_type=IndependentEvaluation)
            response=await Runner.run(reviewer,json.dumps(packet),max_turns=2,run_config=RunConfig(tracing_disabled=True));audit=response.final_output.model_dump()
        results.append({'id':row['id'],'name':row['name'],'audit':audit,'original_review_file':str(path),'evidence_tool_calls':len(evidence),'packet':packet});print(row['name'],audit,flush=True)
    Path('runtime/phase3/complete-evidence-audit.json').write_text(json.dumps(results,indent=2))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--env-file',type=Path,required=True);args=p.parse_args();asyncio.run(run(configuration(args.env_file,True)))
