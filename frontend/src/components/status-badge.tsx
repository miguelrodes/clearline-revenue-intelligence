import {label} from '@/lib/api';
export function statusTone(value:string){
 if(['internal_investigation','running','analyzing_reply'].includes(value))return 'investigating';
 if(['human_verification','needs_contact','needs_information','pending','requires_verification'].includes(value))return 'verification';
 if(['ready','awaiting_approval','approved','queued','scheduled','replied','awaiting_response','needs_review'].includes(value))return 'action';
 if(['completed','resolved','won','sent_simulated','delivered'].includes(value))return 'complete';
 if(['failed','blocked_config','agent_held','needs_attention'].includes(value))return 'blocked';
 return 'neutral';
}
export function StatusBadge({value,text}:{value:string;text?:string}){return <span className={`badge workflow-status status-${statusTone(value)}`}>{text||label(value)}</span>}
