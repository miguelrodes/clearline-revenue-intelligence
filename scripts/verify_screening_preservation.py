"""Compare original databases/CSVs with the read-only integration snapshots."""
import hashlib,json,sqlite3,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];folder=ROOT/'runtime/phase3'
manifest=json.loads((folder/'preservation.json').read_text());result={}
def content(con,table):
 rows=con.execute('SELECT * FROM "'+table.replace('"','""')+'" ORDER BY rowid').fetchall()
 return {'rows':len(rows),'sha256':hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest()}
for name in ('live','phase3'):
 original=sqlite3.connect('file:'+manifest[name]['source']+'?mode=ro',uri=True);snapshot=sqlite3.connect(folder/(name+'-preserved.sqlite3'))
 tables=[r[0] for r in snapshot.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
 differences=[t for t in tables if content(original,t)!=content(snapshot,t)]
 result[name]={'tables_compared':len(tables),'differences':differences,'business_data_unchanged':not(set(differences)-{'worker_state'})};assert result[name]['business_data_unchanged'],(name,differences)
 original.close();snapshot.close()
result['csv_unchanged']=all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in manifest['csv'].items());assert result['csv_unchanged']
preview=sqlite3.connect(folder/'screening.sqlite3');snapshot=sqlite3.connect(folder/'live-preserved.sqlite3')
preserved=['opportunities','drafts','approvals','outbox','outcomes','prospect_research','research_sources','contact_clearance_notes','contact_authorizations']
result['preview_preserved_business_tables']={t:content(preview,t)==content(snapshot,t) for t in preserved};assert all(result['preview_preserved_business_tables'].values())
phase3=sqlite3.connect(folder/'phase3-preserved.sqlite3')
result['original_screening_rows_retained']=content(preview,'agency_screenings')==content(phase3,'agency_screenings')
result['original_qualifications_retained']=all(preview.execute('SELECT * FROM agency_qualifications WHERE job_id=?',(r[0],)).fetchone()==r for r in phase3.execute('SELECT * FROM agency_qualifications'))
assert result['original_screening_rows_retained'] and result['original_qualifications_retained']
result['integrity']=preview.execute('PRAGMA integrity_check').fetchone()[0];result['foreign_key_errors']=preview.execute('PRAGMA foreign_key_check').fetchall();assert result['integrity']=='ok' and not result['foreign_key_errors']
source=Path('/Users/miguelrodes/Code/clearline-revenue-intelligence')
result['preserved_contact_fix']=all((ROOT/p).read_bytes()==(source/p).read_bytes() for p in ('src/clearline/evidence.py','tests/test_contact_clearance.py'));assert result['preserved_contact_fix']
for path,head in ((source,'030209a'),(Path('/Users/miguelrodes/Code/clearline-phase3'),'d151d76')):
 actual=subprocess.check_output(['git','rev-parse','--short','HEAD'],cwd=path,text=True).strip();assert actual==head
 result[path.name+'_head']=actual
result['preserved_uncommitted_patch']=subprocess.check_output(['git','diff','--binary'],cwd=source)==Path('/private/tmp/clearline-preserved-contact.patch').read_bytes();assert result['preserved_uncommitted_patch']
(folder/'preservation-final.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
