'use client';
import {useState} from 'react';
import {request,refresh} from '@/lib/api';

const choices = [
  ['accepted', 'Accept for pursuit'],
  ['held', 'Hold pending a check'],
  ['rejected', 'Reject prospect'],
] as const;

export function ProspectDecision({id, busy, onBusy, onNotice}: {
  id: string;
  busy: boolean;
  onBusy: (busy:boolean) => void;
  onNotice: (message:string) => void;
}) {
  const [rationale,setRationale] = useState('');
  async function decide(decision: typeof choices[number][0]) {
    if (busy || !rationale.trim()) return;
    onBusy(true);
    try {
      await request(`/screening/agencies/${encodeURIComponent(id)}/decision`, 'POST', {decision,rationale});
      onNotice(decision === 'accepted' ? 'Accepted for internal pursuit. Outreach still needs separate approval.'
        : decision === 'held' ? 'Prospect put on hold. Your reason was saved.' : 'Prospect rejected. Your reason was saved.');
      refresh();
    } catch (error) {
      onNotice((error as Error).message);
    } finally {
      onBusy(false);
    }
  }
  return <>
    <label>Reason or specific check needed<textarea value={rationale} disabled={busy}
      onChange={e=>setRationale(e.target.value)} placeholder="Explain why to pursue, what needs checking, or why to discard."/></label>
    <div className="button-row">{choices.map(([value,title])=><button key={value} type="button" className="action-link"
      disabled={busy||!rationale.trim()} onClick={()=>decide(value)}>{title}</button>)}</div>
  </>;
}
