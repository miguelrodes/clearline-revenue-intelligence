export const pipelinePath = '/prospect-pipeline';
export const origins = {
 fictional_csv:'Fictional agency file', real_web:'Web discovery', real_manual:'Previously identified real prospect',
} as const;
export const stages:Record<string,string> = {
 discovered:'Discovered', screened:'Screened', selected_for_research:'Selected for research', research_in_progress:'Research in progress',
 research_completed:'Research completed', needs_verification:'Needs verification',hold:'On hold',rejected:'Rejected',
 awaiting_delivery:'Approved · awaiting simulated delivery',awaiting_approval:'Awaiting approval',
 awaiting_response:'Awaiting response',in_conversation:'In conversation',follow_up:'Follow-up',
 latest_discovery:'Latest discovery results',awaiting_research:'Awaiting research', researched:'With completed research',high_priority:'High investigation priority',
};
export function display(value?:string|null){return value ? stages[value] || value.replaceAll('_',' ').replace(/^./,c=>c.toUpperCase()) : 'Unknown'}
export type Candidate = {
 id:string; name:string; state:string; segment:string; origin:keyof typeof origins; stage:string; qualification:string;
 score:number|null; factors:{key:string;label:string;points:number;maximum:number;reason:string}[];
 reason:string;comparison:string;next_action:string;href:string;detail_href?:string;action_href?:string;verified:boolean;researchable:boolean;researched:boolean;manual_decision?:string;score_version?:string;
};
export type Source={url:string;title?:string;retrieved_at?:string;identity_quote?:string};
export type ProspectProgress={stage:string;next_action:string;latest_activity?:{label:string;at:string|null}};
export type CandidateDetail=Candidate & {
 latest_activity?:ProspectProgress['latest_activity'];
 sources:Source[]; attributes:Record<string,unknown>; field_sources:Record<string,unknown>;limitations?:string[];missing_fields:string[];identity_confidence:string;
 outreach_permission_required:boolean; outreach_authorization?:unknown;research?:unknown; assessment?:unknown;
 draft?:{id:string;version:number;subject:string;body:string;status:string}|null;
};
export type PipelineAction={id:string;title:string;description:string;button_label:string;href:string;count:number|null};
export type Pipeline = {
 filters?:{segments?:string[];qualifications?:string[]};metrics:Record<string,number>;brief:string[];actions:PipelineAction[];rows:Candidate[];total:number;offset:number;limit:number;
};
export const metrics=[
 ['total','All candidates','',
  'Every institution in the pipeline, including fictional agencies and real prospects at every stage.'],
 ['fictional_csv','Fictional agency records','origin=fictional_csv',
  'Institutions from the case study’s public agencies file, used to practice screening and qualification.'],
 ['real_web','Discovered online','origin=real_web',
  'Real institutions first added by Clearline’s discovery search after it checked their identities against official sources.'],
 ['real_manual','Previously identified','origin=real_manual',
  'Real institutions added to the prospect list by hand. Their identity and research status are checked separately.'],
 ['high_priority','High priority','stage=high_priority',
  'Eligible candidates with a screening score of 70 or higher out of 100. These are priorities for investigation. Buying interest still needs confirmation.'],
 ['awaiting_research','Awaiting research','stage=awaiting_research',
  'Verified real institutions ready to select for in-depth research. No current report is available and no investigation is underway.'],
 ['research_completed','Research completed','stage=researched',
  'Real prospects with a current, saved research report. Open an institution to read the findings and sources.'],
 ['awaiting_approval','Awaiting outreach review','stage=awaiting_approval',
  'Candidates with a prepared email waiting for your approval before it can go to the simulated outbox.'],
 ['awaiting_response','Awaiting response','stage=awaiting_response',
  'Candidates waiting for a reply after simulated delivery or a recorded contact attempt. Includes follow-ups that are due.'],
 ['in_conversation','In conversation','stage=in_conversation',
  'Candidates with a recorded reply or a conversation that has moved forward, such as a request for a quote.'],
] as const;
