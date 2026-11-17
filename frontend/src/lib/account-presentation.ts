import type {Account, SavedCommercialSignal} from './types';

export const exactMoney=(cents:number)=>new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',minimumFractionDigits:2,maximumFractionDigits:2}).format(cents/100);
export function plainEnglish(text:string){return text.replace(/an explicit open_orders_require_review hold/g,'pending orders that need checking').replace(/\bopen_orders_require_review\b/g,'pending orders to check').replace(/\bundated_history\b/g,'missing purchase dates').replace(/\bknown_distributor_channel\b/g,'purchases through distributors').replace(/establish (?:the )?disposition/gi,'confirm the current status').replace(/current disposition/gi,'current status').replace(/\bdisposition\b/gi,'status').replace(/revenue-operations/gi,'sales operations').replace(/house-account steward/gi,'account owner').replace(/fulfillment SLA/gi,'promised delivery date').replace(/^[a-z]/,c=>c.toUpperCase());}
export function recommendationIntroduction(a:Account){
 const d=a.assessment?.details;if(!d)return '';
 if(d.decision==='no_action'||a.status==='no_action')return 'The saved review found no justified sales action for this account at present.';
 if(a.status==='monitor'||d.decision==='monitor')return 'The saved review recommends monitoring this account rather than starting outreach now.';
 const orders=[...new Set((a.evidence.commercial_signals||[]).filter(s=>s.category==='aging_open_order').map(s=>s.evidence?.order_id).filter(Boolean))];
 if(orders.length&&/order|fulfill|disposition/i.test(`${d.objective||''} ${d.recommended_action}`))return `${orders.length} ${orders.length===1?'order remains':'orders remain'} recorded as open; confirming their status will show whether any internal issue still needs resolving before the order can be completed. Their age alone does not prove a delay.`;
 if(a.evidence.signals?.some(s=>s.type==='inactivity'))return 'There is a gap in identified purchasing, so the saved review considers whether the purchasing relationship can be reestablished; purchases through an unidentified distributor may be missing from this history.';
 if((a.evidence.prior_cents??0)>(a.evidence.current_cents??0))return 'Recorded purchasing has fallen, so the saved review considers whether there is a justified way to address the change; the decline alone does not establish its cause or how much could be recovered.';
 return '';
}

type Task={title:string;reason:string;owner:string;evidence_refs:string;contact_check?:boolean};
export function verificationExplanation(task:Task,signals:SavedCommercialSignal[]=[]){
 let refs:string[]=[];try{refs=JSON.parse(task.evidence_refs)}catch{}
 const ids=new Set(`${task.title} ${task.reason}`.match(/\bSO-\d+(?:-CR)?\b/g)||[]);
 const orders=[...new Map(signals.filter(s=>s.category==='aging_open_order'&&s.evidence?.order_id&&(ids.has(s.evidence.order_id)||!!s.evidence.rows?.length&&s.evidence.rows.every(r=>refs.includes(r)))).map(s=>[s.evidence!.order_id,s])).values()];
 if(orders.length){
  const amount=orders.every(s=>typeof s.amount_cents==='number')?orders.reduce((n,s)=>n+s.amount_cents!,0):null;
  return {context:`${orders.map(s=>s.evidence!.order_id).join(', ')} ${orders.length===1?'has':'have'} lines still recorded as open. Confirm whether they were fulfilled, invoiced, canceled, or remain on hold so any unresolved issue can be addressed; age alone does not establish lateness.`,next:'Ask the suggested team to check the records below and record the confirmed status, supporting evidence, and any corrective action needed.',financial:amount!==null?`${exactMoney(amount)} in recorded open-order value; not confirmed lost or recoverable revenue.`:null};
 }
 if(/credit|refund|billing/i.test(task.title)){
  const credits=signals.filter(s=>s.evidence?.credit_rows?.length&&s.evidence.credit_rows.every(r=>refs.includes(r)));
  const amount=credits.length===1?credits[0].amount_cents:null;
  return {context:'The saved review asks for the reason and resolution of historical billing or credit records. Confirm what happened before using them as a reason for customer outreach; a credit alone does not establish dissatisfaction.',next:'Ask the suggested team to link the original invoice and any adjustment, replacement, or closure evidence.',financial:amount!=null?`${exactMoney(Math.abs(amount))} in historical credit value; these credits reduce recorded net revenue and are not a recovery estimate.`:null};
 }
 if(task.contact_check)return {context:'This check concerns who may discuss purchasing and which buying route is permitted. Confirming the requested information helps any later outreach reach the appropriate person while respecting the existing relationship.',next:'Use approved internal records to verify the contact, role, purchasing route, and supporting evidence requested below.',financial:null};
 return {context:plainEnglish(task.reason),next:null,financial:null};
}

export type RevenueContext={historical_decline_cents:number|null;metric:'positive_account_net_purchasing_decline';comparison:{current_start:string;current_end_exclusive:string;prior_start:string;prior_end_exclusive:string}|null;total_accounts:number;accounts:number;excluded_distributor_accounts:number;excludes_distributors:boolean;unavailable_reason:string|null};
type BriefAction={id:string;why:string;accounts:number;financial_cents?:number|null;historical_decline_cents?:number|null;financial_label?:string;revenue_context?:RevenueContext};
export function actionFinancialCents(a:Pick<BriefAction,'revenue_context'|'financial_cents'|'historical_decline_cents'>){return a.revenue_context?a.revenue_context.historical_decline_cents:a.financial_cents??a.historical_decline_cents;}
export function comparisonPeriod(comparison:RevenueContext['comparison']){
 if(!comparison)return 'the saved comparable periods';
 const period=(start:string,end:string)=>{
  const from=new Date(`${start}T00:00:00Z`),exclusive=new Date(`${end}T00:00:00Z`),last=new Date(exclusive.getTime()-86400000);
  const month=(d:Date)=>d.toLocaleDateString('en-US',{month:'long',timeZone:'UTC'});
  if(from.getUTCDate()===1&&exclusive.getUTCDate()===1&&from.getUTCFullYear()===last.getUTCFullYear())return `${month(from)}${from.getUTCMonth()===last.getUTCMonth()?'':`–${month(last)}`} ${from.getUTCFullYear()}`;
  const full=(d:Date)=>d.toLocaleDateString('en-US',{month:'short',day:'numeric',year:'numeric',timeZone:'UTC'});
  return `${full(from)}–${full(last)}`;
 };
 return `${period(comparison.current_start,comparison.current_end_exclusive)} versus ${period(comparison.prior_start,comparison.prior_end_exclusive)}`;
}
export function actionDescription(a:BriefAction,asOf?:string){
 let text=plainEnglish(a.why);
 if(a.id==='contacts'||a.id==='investigation:contacts')text=`These ${a.accounts} accounts have purchasing-contact or relationship information that needs verification. Record the missing details so Clearline can determine where outreach is justified and who may receive it.`;
 else if(a.id==='investigation:orders')text=`These ${a.accounts} accounts have order or credit records that need clarification. Ask the named internal owners to confirm their status so Clearline can address unresolved issues before further outreach.`;
 else if(a.id==='investigation:needs')text=`These ${a.accounts} accounts have recorded training, product or purchasing questions. Confirm with the named owners which needs remain relevant so the agent can recommend appropriate support.`;
 else if(a.id==='investigation:records')text=`These ${a.accounts} accounts have unresolved questions in their saved reviews. Record supported answers from the named owners so the agent can determine the appropriate next step.`;
 if(a.id==='investigation:orders')text+=' Checking what shipped, what was canceled and why credits were issued could uncover a billing or delivery problem that Clearline can fix to protect a pending order or keep the customer’s trust.';
 else if(a.id==='investigation:contacts')text+=' Reconnecting with the right buyer through the authorized channel could reveal a change in how the customer buys or a supply need that leads to a reorder.';
 else if(a.id==='investigation:needs')text+=' If the customer confirms a need, training or product support could earn repeat business, while a supply gap could justify replenishment or an additional product.';
 else if(a.id==='investigation:records')text+=' Separating billing, identity or data errors from genuine purchasing obstacles helps salespeople focus on declines they may be able to reverse.';
 const context=a.revenue_context;
 if(context){
  if(context.historical_decline_cents==null)return `${text} ${context.unavailable_reason||'Comparable purchasing figures are unavailable for these records.'}`;
  const scope=`${context.accounts} non-distributor account${context.accounts===1?'':'s'}`;
  const period=comparisonPeriod(context.comparison);
  if(context.historical_decline_cents<=0)return `${text} The ${scope} show no positive recorded purchasing decline (${period}); the checks may still resolve operational or relationship questions.`;
  const qualification=a.id==='investigation:orders'?'This is historical decline, not an outstanding-order or credit balance or a recovery forecast':a.id==='investigation:needs'?'This is historical account decline, not training revenue or an estimate of new sales':'This is historical decline associated with these accounts, not a recovery forecast';
  return `${text} Across ${scope}, positive purchasing declines total ${exactMoney(context.historical_decline_cents)} (${period}). ${qualification}; groups overlap and must not be added.`;
 }
 const value=a.financial_cents??a.historical_decline_cents;
 if(value==null)return `${text} No comparable purchasing total is attached to these records.`;
 if(value<=0)return text;
 const period=asOf&&/^\d{4}-11-01$/.test(asOf)?`January–October ${Number(asOf.slice(0,4))-1} versus ${asOf.slice(0,4)}`:'the saved comparable periods';
 if(!a.financial_label||/decline/i.test(a.financial_label))return `${text} The displayed ${exactMoney(value)} sums the positive account-level purchasing declines associated with this group (${period}), rather than the value of the checks themselves. It is historical deterioration, not forecast recovery; groups can overlap and their amounts must not be added.`;
 if(/open|outstanding/i.test(a.financial_label))return `${text} The displayed ${exactMoney(value)} is recorded open-order value, not booked revenue or confirmed lost sales. Completion and any recoverable amount remain unverified.`;
 return `${text} The displayed ${exactMoney(value)} is labeled “${a.financial_label}”; it is not a forecast of recovery.`;
}

type ConversationMessage={direction:string;subject:string;body:string;created_at:string;status:string;simulated?:number;provider?:string;interpretation?:{intent:string;recommended_action:string}|null};
export function conversationSummary(t:{provider?:string;messages:ConversationMessage[];status:string},crmNote?:string){
 const latest=t.messages.at(-1);
 if(!latest)return `No customer conversation has been recorded.${crmNote?' An undated internal CRM note is available in the account history; it is not a recorded customer exchange.':''}`;
 const simulated=t.provider==='simulated'||latest.provider==='simulated'||latest.simulated===1||latest.status==='sent_simulated';
 const subject=latest.subject?.trim();
 const topic=subject?`about “${subject}”`:'with no subject recorded';
 const prefix=simulated?'The latest simulated exchange':'The latest recorded exchange';
 const ending=latest.direction==='outbound'? 'No subsequent customer reply is recorded.' : latest.interpretation?`The saved AI interpretation recommends: ${plainEnglish(latest.interpretation.recommended_action)}`:'A customer reply is recorded, but no AI interpretation is saved yet.';
 return `${prefix} ${topic} ${latest.direction==='outbound'?'was an outgoing email':'was a customer reply'}. ${ending}`;
}

export type TaskInquiryState = 'draft' | 'status_requested' | 'response_recorded';
export const taskInquiryLabel: Record<TaskInquiryState, string> = {
 draft: 'Internal email prepared for review',
 status_requested: 'Internal request sent · awaiting response',
 response_recorded: 'Internal reply recorded · verify the finding',
};
