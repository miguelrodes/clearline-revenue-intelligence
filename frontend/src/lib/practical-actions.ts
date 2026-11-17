export type PracticalTask={id:string;title:string;question:string;record_refs:string[];record_ids:string[];blocking:boolean};
export type PracticalAction={id:string;category:'orders'|'contacts'|'needs'|'records';role_key:string;role:string;title:string;found:string;why:string;next_step:string;afterward:string;control:'finding'|'contact';can_prepare_internal:boolean;assigned_owner?:string|null;task_ids:string[];tasks:PracticalTask[];lines:{ref:string;order_id:string;sku:string;qty:string;date:string;status:string;amount_cents:number|null;age_days:number|null}[];missing_contact_fields?:string[]};
export type ReviewJob={id:string;status:string;error?:string|null;finished_at?:string|null};
type CheckState='draft'|'status_requested'|'response_recorded'|'verified'|'closed';
type WorkflowState='awaiting_approval'|'awaiting_response'|'response_recorded'|'partially_verified'|'verified'|'closed';
export type InquiryReply={id:string;body:string;record_refs:string[];confirmed_task_ids:string[];suggested_finding?:string;suggested_findings?:Record<string,string>;confirmations?:{task_id:string;finding:string;source:string;confirmed_at?:string}[]};
export type InternalInquiry={id:string;group_id:string;role_key?:string;responsibility:string;task_ids:string[];pending_task_ids:string[];tasks:PracticalTask[];lines:PracticalAction['lines'];recipient:string;subject:string;body:string;version:number;snapshot_hash:string;status:string;replies:InquiryReply[];job_id:string|null;
 workflow_state?:WorkflowState;sent_at?:string|null;sent_version?:number|null;
 record_states?:{order_id:string;line_refs:string[];task_ids:string[];status:CheckState}[];
 task_states?:{task_id:string;status:CheckState;finding:string|null}[];
 previous_versions?:{version:number;subject:string;body:string;recipient:string;created_at:string}[];
 reassessment_status?:string|null};
export type InquiryData={recipients:{group_id:string;responsibility:string;role_key:string;recipient:string;evidence:string}[];inquiries:InternalInquiry[]};
export const practicalAnchor=(id:string)=>`check-${id}`;
export function recordCoverage(task:PracticalTask,lines:PracticalAction['lines'],finding:string){
 const cited=new Set(finding.toUpperCase().match(/[\w-]+/g)||[]);
 return task.record_ids.every(id=>{
  if(!cited.has(id.toUpperCase()))return false;
  const referenced=lines.filter(l=>l.order_id===id&&task.record_refs.includes(l.ref));
  return referenced.length<2||referenced.every(l=>cited.has(l.sku.toUpperCase()))||/\b(?:all|both|every) (?:of (?:the |its ))?(?:(?:open|credit|recorded) )?(?:lines?|items?)\b/i.test(finding);
 });
}
export function reviewStatus(job:ReviewJob|null|undefined){
 if(!job)return '';
 if(['queued','running'].includes(job.status))return job.status==='running'?'Clearline is reassessing this account. The updated recommendation will appear here.':'A review of this account is queued. The recommendation will update here.';
 if(['failed','blocked_config'].includes(job.status))return `The latest account review could not finish${job.error?`: ${job.error}`:'.'} Check Agent activity before relying on the previous recommendation.`;
 return '';
}


export function currentInquiries(action:PracticalAction,data?:InquiryData){
 return (data?.inquiries??[]).filter(i=>i.group_id===action.id
  && ['awaiting_approval','sent_simulated','reply_recorded'].includes(i.status)
  && (i.status!=='awaiting_approval'||action.can_prepare_internal)
  && i.pending_task_ids.some(id=>action.task_ids.includes(id)));
}

export function sentScope(inquiry:InternalInquiry){
 const orders=new Set(inquiry.lines.map(line=>line.order_id)).size;
 if(!orders)return `${inquiry.tasks.length} ${inquiry.tasks.length===1?'check':'checks'}`;
 const credit=inquiry.lines.every(line=>line.status.toLowerCase().includes('credit'));
 return `${orders} ${credit?'credit':'order'}${orders===1?'':'s'} (${inquiry.lines.length} ${inquiry.lines.length===1?'line':'lines'})`;
}

export function replyTasks(reply:InquiryReply,inquiry:InternalInquiry,allowed:string[]){
 return inquiry.tasks.filter(t=>allowed.includes(t.id)&&inquiry.pending_task_ids.includes(t.id)
  && !reply.confirmed_task_ids.includes(t.id)
  && (reply.record_refs.length ? t.record_ids.some(id=>reply.record_refs.includes(id)) : !reply.confirmed_task_ids.length));
}

export function inquiryNext(action:Pick<PracticalAction,'role_key'|'role'|'control'|'task_ids'>,inquiry:InternalInquiry){
 if(inquiry.status==='awaiting_approval')return {title:'Review the internal email',text:`The draft for ${action.role.toLowerCase()} covers ${sentScope(inquiry)}. Check the recipient and message before approving simulated delivery.`};
 const records=inquiry.record_states??[], verified=records.filter(r=>r.status==='verified'), remaining=records.filter(r=>['status_requested','response_recorded'].includes(r.status));
 const pendingReply=inquiry.replies.some(r=>replyTasks(r,inquiry,action.task_ids).length);
 const noun=action.role_key==='fulfillment'?'order':action.role_key==='billing'?'credit':'record';
 const coverage=verified.length?`${verified.length===1?verified[0].order_id+' has a verified finding':verified.length+' records have verified findings'}. ${remaining.length} ${noun}${remaining.length===1?' still needs':'s still need'} confirmation. `:'';
 if(pendingReply)return {title:action.control==='contact'?'Verify the purchasing details in the reply':'Review and record the finding',text:coverage+(action.control==='contact'?'Check the reported recipient and buying route against an authorized source before enabling outreach.':'An internal reply was recorded. Check it against supporting records and confirm only the findings you can verify.')};
 const title=action.role_key==='fulfillment'?'Awaiting fulfillment update':action.role_key==='billing'?'Awaiting billing update':'Awaiting an internal response';
 return {title,text:coverage||`The simulated request to ${inquiry.recipient} covers ${sentScope(inquiry)}. Wait for a response before deciding what needs attention.`};
}
