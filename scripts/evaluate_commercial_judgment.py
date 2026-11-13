"""Reproducible balanced commercial eval. Synthetic authorization exists ONLY in this isolated fixture.
Expected decisions are fixed before model execution; scorer never supplies them to the investigator.
All source fixtures, outputs, costs and independent review are retained. No approval/send calls.
"""
import asyncio,csv,json,os,hashlib,argparse
from pathlib import Path
from dataclasses import replace,asdict
from datetime import date,timedelta
from dotenv import load_dotenv
from clearline.config import Settings
from clearline.store import Store,utcnow
from clearline.data import scan,ScanPolicy,digest
from clearline.commercial import detect,CommercialPolicy,associations
from clearline.commercial_agent import investigate
from clearline.agent import RecoveryDecision,Strict
from clearline.worker import execute_job
from clearline.operations import latest_assessment

ROOT=Path(__file__).resolve().parents[1]
CATEGORIES=['inactive_recovery','purchasing_decline','sku_deterioration','missed_replenishment','distributor_recovery','aging_open_order','cross_sell','purchasing_obstacle','churn_prevention','association']

def build(folder,include_boundary=False):
    folder.mkdir(parents=True,exist_ok=True);cases=[];orders=[];crm=[];public=[]
    for category in CATEGORIES:
      for positive in (True,False):
       for variant in range(2):
        number=len(cases)+1;name=f'Evaluation {number:02} County Jail';cid=f'eval-{number:02}';notes='';last='2026-07-01';rows=[];channel='direct'
        def order(day,qty=100,sku='CL-FS10',status='invoiced'):
            rows.append([f'{cid}-SO-{len(rows)+1}',day,name,'','Fixture City','MA',channel,sku,str(qty),'100',str(qty*100),status])
        def healthy():
            for y in (2025,2026):
                for month in (1,4,7,10):order(f'{y}-{month:02}-20')
        expected=['contact'] if positive else ['no_action','monitor','defer'];why='';must=[]
        if category=='inactive_recovery':
            if positive:
                for month in (1,4,7,10):order(f'2025-{month:02}-20')
                order('2026-01-20');why='Established repeat purchases stopped; authorized purchasing contact; useful need check now.'
            else:healthy();why='Stable comparable purchasing with recent invoice; no separate need.'
        elif category=='purchasing_decline':
            for y in (2025,2026):
                for month in (1,4,7,10):order(f'{y}-{month:02}-20',40 if positive and y==2026 else 100)
            why='Large physical and revenue decline with a verified buying relationship.' if positive else 'Stable revenue and physical quantities, no trigger.'
        elif category=='sku_deterioration':
            for y in (2025,2026):
                for month in (4,7,10):
                    order(f'{y}-{month:02}-20',10 if positive and y==2026 else 100)
                    order(f'{y}-{month:02}-20',200 if positive and y==2026 else 100,'CL-MAIL50')
            why='Fentanyl swabs dropped despite mailroom growth; a product-specific need check is justified.' if positive else 'Both products stable; missing demand must not be invented.'
        elif category=='missed_replenishment':
            dates=['2026-05-01','2026-06-01','2026-07-01','2026-08-01'] if positive else ['2025-01-01','2025-01-02','2026-01-01','2026-10-25']
            for day in dates:order(day)
            why='Consistent monthly replenishment stopped beyond 1.5x the established cycle.' if positive else 'Irregular annual and adjacent purchases do not establish a monthly replenishment pattern.'
        elif category=='distributor_recovery':
            channel='distributor'
            for y in (2025,2026):
                for month in (4,7,10):order(f'{y}-{month:02}-20',40 if positive and y==2026 else 100)
            why='Verified distributor own purchasing decline; authorized distributor buyer; no aged orders.' if positive else 'Distributor own purchases stable; do not fabricate downstream support needs.'
        elif category=='aging_open_order':
            healthy();order('2026-07-01' if positive else '2026-11-01',40,'CL-FS10','open')
            if positive:expected=['internal_investigation'];must=['order']
            why='Old open order requires internal disposition research; no fulfillment SLA known.' if positive else 'Same-day open order plus healthy purchasing is not overdue or a customer-contact reason.'
        elif category=='cross_sell':
            healthy();notes='Interested in mailroom kits; active mailroom screening program. Buyer asked for a product suitability discussion.' if positive else ''
            why='Explicit interest in a never-purchased mailroom product supports a bounded suitability discussion.' if positive else 'No mailroom purchase alone is not cross-sell demand.'
        elif category=='purchasing_obstacle':
            healthy();notes='Wants training for night shift; current need confirmed, no training completed.' if positive else 'Night shift training request was completed on October 24. Staff confirmed issue resolved; no further help needed.'
            last='2026-10-24' if not positive else '2026-10-30'
            why='Documented current training need can protect or expand existing use despite stable revenue.' if positive else 'Resolved training concern plus recent contact does not justify another support email.'
        elif category=='churn_prevention':
            healthy()
            if positive:
                order('2026-10-25',-10,'CL-FS10','credit_memo');expected=['internal_investigation'];must=['credit']
                why='Unexplained credit requires invoice/reason review before customer contact; not proof of dissatisfaction.'
            else:why='Healthy purchasing, no complaints or credits; no churn reason.'
        elif category=='association':
            healthy();why='Reliable association in a separate, documented synthetic peer population and relevant screening operation justifies suitability discussion.' if positive else 'Weak association and no product interest cannot justify cross-sell.'
            if positive:notes='Operates a mailroom screening program; purchasing contact authorized to discuss suitable screening products.'
        # Distinct evidence variants, fixed before execution (not duplicate names).
        # Boundary negatives deliberately exercise strict >25% detection.
        if category=='purchasing_obstacle' and positive:
            expected=['human_verification']
            why='An undated CRM training note and recent contact require checking whether the need remains current before contacting the buyer again.'
        if variant:
            if category=='inactive_recovery':
                if positive:rows[-1][1]='2026-03-20'
                else:rows[-1][1]='2026-10-28';rows[-1][8]='120';rows[-1][10]='12000'
            elif category=='purchasing_decline':
                for row in rows:
                    if row[1].startswith('2026'):row[8]=str(30 if positive else 75);row[10]=str(int(row[8])*100)
                if not positive:why='An exactly 25% decline does not exceed the documented material-decline threshold; recent regular purchasing and no independent obstacle.'
            elif category=='sku_deterioration':
                for row in rows:
                    if row[1].startswith('2026'):
                        row[8]=str((20 if positive else 75) if row[7]=='CL-FS10' else (240 if positive else 125));row[10]=str(int(row[8])*100)
                if not positive:why='The swab reduction is exactly 25%, below the strict qualifying rule, offset by mailroom growth; no independent intervention reason.'
            elif category=='missed_replenishment':
                rows=[]
                for day in (['2026-01-01','2026-02-01','2026-03-01','2026-04-01'] if positive else ['2026-10-15']):order(day,50)
                if not positive:why='A single recent order does not establish an overdue replenishment cycle or an inactive established customer.'
            elif category=='distributor_recovery':
                for row in rows:
                    if row[1].startswith('2026'):row[8]=str(50 if positive else 120);row[10]=str(int(row[8])*100)
                if not positive:why='Distributor own purchases grew; no downstream support or recovery need is established.'
            elif category=='aging_open_order':
                rows[-1][1]='2026-09-01' if positive else '2026-10-27';rows[-1][8]='10';rows[-1][10]='1000'
                if not positive:why='A five-day open order is below the transparent age threshold and has no independent delay evidence.'
            elif category=='cross_sell':
                if positive:notes='Interested in mailroom kits for a documented screening operation. Buyer asked to compare kit suitability with their current swabs.';order('2026-10-25',20)
                else:order('2024-10-01',100,'CL-MAIL50');why='The supposedly missing mailroom product was already purchased outside the comparison windows; no new product interest or suitable cross-sell evidence.'
            elif category=='purchasing_obstacle':
                if positive:notes='Wants training for new staff on mailroom handling; no independent date or completion record is available.'
                else:notes='Purchasing contact change resolved on October 24. Replacement buyer is established and the regular October order is complete; no assistance requested.'
            elif category=='churn_prevention':
                if positive:rows[-1][8]='-25';rows[-1][10]='-2500';rows[-1][1]='2026-09-25'
                else:order('2026-10-28',50)
            elif category=='association':
                order('2026-10-28',30)
        crm.append([cid,name,'MA','Evaluation account owner',notes,last]);public.append([name,'MA','Fixture City']);orders.extend(rows)
        cases.append(dict(case_id=cid,name=name,category=category,positive=positive,expected_outcomes=expected,expected_reason=why,required_topics=must,synthetic=True,variant=variant))
    # Additional independent boundary cases keep all earlier results while
    # increasing unique evidence coverage (some healthy negatives intentionally overlap).
    for offset,(category,positive) in enumerate([('sku_deterioration',True),('purchasing_decline',False),('aging_open_order',True),('aging_open_order',False)] if include_boundary else [],1):
        name=f'Boundary {offset:02} County Jail';cid=f'boundary-{offset:02}';rows=[];channel='direct'
        for y in (2025,2026):
            for month in (1,4,7,10):
                qty=50 if offset==1 and y==2026 else 100
                price=150 if offset==1 and y==2026 else 95 if offset==2 and y==2026 else 100
                rows.append([f'{cid}-SO-{len(rows)+1}',f'{y}-{month:02}-20',name,'','Boundary City','MA',channel,'CL-FS10',str(qty),str(price),str(qty*price),'invoiced'])
        if offset in (3,4):rows.append([f'{cid}-OPEN','2026-10-02' if offset==3 else '2026-10-03',name,'','Boundary City','MA',channel,'CL-FS10','15','100','1500','open'])
        expected=['contact'] if offset==1 else ['internal_investigation'] if offset==3 else ['no_action','monitor','defer']
        reasons={1:'Physical swab quantities fell 50% despite a price increase that leaves net revenue down only 25%; a product-specific discussion is justified.',2:'Prices fell 5% with unchanged physical quantities and cadence; no material purchasing deterioration or independent intervention reason.',3:'The open order is exactly 30 days old at the cutoff; the explicit investigation threshold applies without implying an overdue SLA.',4:'The open order is 29 days old, below the documented investigation threshold; no delay evidence or purchasing deterioration.'}
        orders.extend(rows);crm.append([cid,name,'MA','Evaluation account owner','','2026-07-01']);public.append([name,'MA','Boundary City'])
        cases.append(dict(case_id=cid,name=name,category=category,positive=positive,expected_outcomes=expected,expected_reason=reasons[offset],required_topics=['order'] if offset==3 else [],synthetic=True,variant=2))
    files={'orders':(['order_id','order_date','bill_to_account','end_customer','ship_to_city','ship_to_state','sales_channel','sku','qty','unit_price','line_total','status'],orders),'crm_accounts':(['crm_id','account_name','state','owner','notes','last_contacted'],crm),'public_agencies':(['agency_name','state','city'],public),'products':(['sku','name','tests_per_pack','list_price_until_2025_06_30','list_price_from_2025_07_01'],[['CL-FS10','Fentanyl surface swabs',10,100,100],['CL-MAIL50','Mailroom screening kits',50,100,100],['CL-TRN','Training session',0,100,100]])}
    for name,(headers,rows) in files.items():
        with (folder/(name+'.csv')).open('w',newline='') as f:w=csv.writer(f);w.writerow(headers);w.writerows(rows)
    (folder/'expectations.json').write_text(json.dumps(cases,indent=2))
    return cases

async def main():
    p=argparse.ArgumentParser();p.add_argument('--review',action='store_true');p.add_argument('--env-file',type=Path);p.add_argument('--output-dir',type=Path);p.add_argument('--supplemental',action='store_true');args=p.parse_args()
    if args.env_file:load_dotenv(args.env_file)
    folder=args.output_dir or ROOT/'runtime/judgment-53-distinct';cases=build(folder/'sources',include_boundary=args.supplemental)
    cases=[c for c in cases if c['case_id'].startswith('boundary-')==args.supplemental]
    settings=replace(Settings.load(),db_path=folder/'state.sqlite3',data_dir=folder/'sources',concurrency=6,max_concurrency=6,investigation_timeout_seconds=600)
    store=Store(settings.db_path);summary,items=scan(settings.data_dir,include_all=True)
    for case in cases:
        candidates=[i for i in items if i['name']==case['name']]
        item=next(i for i in candidates if i['account_key'].startswith('DISTRIBUTOR|')) if case['category']=='distributor_recovery' else next(i for i in candidates if not i['account_key'].startswith(('DISTRIBUTOR|','UNRESOLVED|')))
        case['account_id']=item['id'];e=item['evidence']
        if case['category']=='association':
            baskets=[{'account_key':f'MA|buyer|peer{i}','products':[{'sku':s,'current_packs_or_sessions':10} for s in (['CL-FS10','CL-MAIL50'] if i<30 else ['CL-FS10'] if i<40 else ['CL-TRN'])]} for i in range(100)] if case['positive'] else [{'account_key':f'MA|buyer|peer{i}','products':[{'sku':s,'current_packs_or_sessions':10} for s in ['CL-FS10','CL-MAIL50']]} for i in range(5)]
            if case['variant']:
                baskets=[{'account_key':f'MA|buyer|peer{i}','products':[{'sku':s,'current_packs_or_sessions':10} for s in (['CL-FS10','CL-MAIL50'] if i<45 else ['CL-FS10'] if i<60 else ['CL-TRN'])]} for i in range(120)] if case['positive'] else [{'account_key':f'MA|buyer|peer{i}','products':[{'sku':s,'current_packs_or_sessions':10} for s in ['CL-FS10','CL-MAIL50']]} for i in range(100)]
            assoc=associations(baskets);e['product_associations']=assoc;e['association_fixture_population']=baskets
            (folder/(case['case_id']+'-association-population.json')).write_text(json.dumps(baskets))
            raw=[]
            with (settings.data_dir/'orders.csv').open() as f:
                for n,row in enumerate(csv.DictReader(f),2):
                    if n in e['source_rows']:raw.append(dict(row,ref=f'orders:{n}'))
            e['commercial_signals']=detect(e,raw,assoc);item['evidence_hash']=digest(e)
        e['evaluation_notice']='Synthetic evaluation case. Named authorization is a fixture fact, not permission to contact any real person.'
        item['evidence_hash']=digest(e)
    selected={c['account_id'] for c in cases};store.save_scan(summary,[i for i in items if i['id'] in selected])
    for case in cases:
        with store.connect(write=True) as c:
            c.execute('INSERT OR IGNORE INTO contact_authorizations VALUES(?,?,?,?,?,?,?)',(case['account_id'],'buyer@example.org','Purchasing manager','direct','Explicit synthetic evaluation authorization for existing buying relationship',1,'2026-11-01'))
    (folder/'expectations.json').write_text(json.dumps(cases,indent=2))
    sem=asyncio.Semaphore(6)
    start=store.rows('SELECT COALESCE(MAX(id),0) n FROM events')[0]['n']
    async def one(case):
      async with sem:
        if store.rows("SELECT 1 FROM controls WHERE name='api_blocked'"):return
        cost=store.rows("SELECT COALESCE(SUM(json_extract(details,'$.cost_usd')),0) n FROM events WHERE id>? AND kind='api_response'",(start,))[0]['n']
        if cost>20:print('COST LIMIT',flush=True);return
        jid=store.queue_analysis(case['account_id'],investigation=True)
        with store.connect(write=True) as c:
            c.execute("UPDATE jobs SET status='running',started_at=?,attempts=attempts+1 WHERE id=? AND status='queued'",(utcnow(),jid))
            job=dict(c.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone());job['payload']=json.loads(job['payload'])
        if job['status']=='running':await execute_job(store,settings,job)
        a=latest_assessment(store,case['account_id']) or {};actual=(a.get('commercial_plan') or {}).get('outcome')
        ok=actual in case['expected_outcomes'] and not a.get('review_failed')
        print(json.dumps({'case':case['case_id'],'category':case['category'],'positive':case['positive'],'actual':actual,'expected':case['expected_outcomes'],'agreement':ok}),flush=True)
    await asyncio.gather(*(one(c) for c in cases))
    results=[]
    for c in cases:
        a=latest_assessment(store,c['account_id']) or {};plan=a.get('commercial_plan') or {}
        results.append({**c,'actual':plan.get('outcome'),'agreement':plan.get('outcome') in c['expected_outcomes'] and not a.get('review_failed'),'assessment':a})
    (folder/'results.json').write_text(json.dumps(results,indent=2))
    print(json.dumps({'total':len(results),'agree':sum(r['agreement'] for r in results),'usage':store.rows("SELECT count(*) calls,SUM(json_extract(details,'$.cost_usd')) cost FROM events WHERE kind='api_response'")}),flush=True)
    if args.review:await independent_review(store,settings,results,folder)

async def independent_review(store,settings,results,folder):
    from agents import Agent,Runner,RunConfig,ModelSettings,OpenAIResponsesModel
    from openai.types.shared import Reasoning
    from clearline.telemetry import client_for
    from pydantic import Field
    class Judgment(Strict):
        case_id:str
        acceptable:bool
        critical_failure:bool
        reason:str
    class Evaluation(Strict):judgments:list[Judgment]
    all_reviews=[]
    # Independent reviewer sees sources + final strategy, NOT supervisor's verdict/scores or expected answer.
    for batch in range(0,len(results),8):
        payload=[]
        for r in results[batch:batch+8]:
            payload.append({'case_id':r['case_id'],'source':store.opportunity(r['account_id'])['evidence'],'authorization':store.rows('SELECT recipient,role,route,evidence FROM contact_authorizations WHERE opportunity_id=?',(r['account_id'],)), 'strategy':r['assessment'].get('commercial_plan'),'email':{k:r['assessment'].get(k) for k in ('subject','body')}})
        job={'id':None,'opportunity_id':None}
        async with client_for(store,job,settings) as client:
            agent=Agent(name='Independent evaluation adjudicator',model=OpenAIResponsesModel(model=settings.model,openai_client=client),output_type=Evaluation,model_settings=ModelSettings(reasoning=Reasoning(effort='high'),max_tokens=6000,store=False),instructions='Independently evaluate each commercial intervention from source evidence. Reject unnecessary contact, invented need, missing prerequisite, wrong recipient/channel, same-day overdue alarms, customer requests to investigate seller records. Approve contact only for a useful specific commercial intervention now. Internal work/no action may be correct. Training or cross-sell can be valuable without decline. These are explicitly synthetic scenarios with fixture authorization. Return every case exactly once; critical failure means unsafe/unsupported external action or material missed intervention, not wording preferences. Do not accept a decision merely because it is labeled approved.')
            output=await Runner.run(agent,json.dumps(payload),max_turns=1,run_config=RunConfig(tracing_disabled=True))
            judgments=[j.model_dump() for j in output.final_output.judgments]
            if {j['case_id'] for j in judgments}!={p['case_id'] for p in payload}:raise ValueError('Independent evaluator omitted a case')
            all_reviews.extend(judgments)
    (folder/'independent-review.json').write_text(json.dumps(all_reviews,indent=2));print(json.dumps({'independent_acceptable':sum(j['acceptable'] for j in all_reviews),'critical_failures':[j for j in all_reviews if j['critical_failure']]}),flush=True)

if __name__=='__main__':asyncio.run(main())
