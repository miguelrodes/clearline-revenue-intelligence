import {describe,it,expect,vi,beforeEach} from "vitest";
import {render,screen,fireEvent,waitFor} from "@testing-library/react";
import type {Draft,Opportunity} from "../src/lib/types";
const params=new URLSearchParams();
vi.mock("next/navigation",()=>({usePathname:()=>"/opportunities",useSearchParams:()=>params,useRouter:()=>({push:vi.fn(),replace:vi.fn()})}));
import {DraftEditor,OpportunityTable} from "../src/components/workspace";
const draft:Draft={id:"test-draft",opportunity_id:"test",version:2,evidence_hash:"hash",recipient:"simulation@example.invalid",subject:"Purchasing check-in",body:"Please confirm the purchasing contact.",status:"awaiting_approval",can_review:true,created_at:"2026-11-11T12:00:00+00:00"};
beforeEach(()=>{vi.restoreAllMocks();params.delete("signal");vi.stubGlobal("fetch",vi.fn().mockResolvedValue({ok:true,json:async()=>({status:"approved",draft_id:"new-version"})}))});
describe("Human approval workflow",()=>{
 it("can confirm immediately after typing and approves the exact newly saved version",async()=>{
  vi.mocked(fetch).mockResolvedValueOnce({ok:true,json:async()=>({draft_id:"edited",version:3})} as Response);
  render(<DraftEditor draft={draft}/>);
  fireEvent.change(screen.getByLabelText("Subject"),{target:{value:"Revised subject"}});
  fireEvent.click(screen.getByRole("button",{name:"Approve simulated send"}));
  expect(screen.getByRole("dialog")).toHaveTextContent("Revised subject");
  expect(fetch).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button",{name:"Confirm"}));
  await waitFor(()=>expect(fetch).toHaveBeenCalledTimes(2));
  const calls=vi.mocked(fetch).mock.calls;
  expect(calls[0][0]).toBe("/api/drafts/test-draft");
  expect(calls[0][1]?.method).toBe("PATCH");
  expect(calls[1][0]).toBe("/api/drafts/edited/decision");
  expect(JSON.parse(calls[1][1]?.body as string)).toEqual({version:3,recipient:draft.recipient,subject:"Revised subject",body:draft.body,approve:true});
 });
 it("never approves merely by opening a draft or approval preview",async()=>{
  render(<DraftEditor draft={draft}/>);
  expect(fetch).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button",{name:"Approve simulated send"}));
  expect(screen.getByRole("dialog")).toBeInTheDocument();
  expect(fetch).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button",{name:"Confirm"}));
  await waitFor(()=>expect(fetch).toHaveBeenCalledOnce());
  expect(JSON.parse(vi.mocked(fetch).mock.calls[0][1]?.body as string)).toEqual({version:2,recipient:draft.recipient,subject:draft.subject,body:draft.body,approve:true});
 });
 it("surfaces rejected stale approval without claiming success",async()=>{
  vi.mocked(fetch).mockResolvedValueOnce({ok:false,json:async()=>({detail:"Opportunity changed or is held; reassess before approval"})} as Response);
  render(<DraftEditor draft={draft}/>);
  fireEvent.click(screen.getByRole("button",{name:"Approve simulated send"}));
  fireEvent.click(screen.getByRole("button",{name:"Confirm"}));
  expect(await screen.findByRole("alert")).toHaveTextContent("Opportunity changed");
  expect(screen.queryByText("Approved. The worker will record the simulated delivery.")).not.toBeInTheDocument();
 });
 it("does not offer approval for a delivered or invalidated draft",()=>{
  render(<DraftEditor draft={{...draft,status:"simulated",can_review:false}}/>);
  expect(screen.queryByRole("button",{name:"Approve simulated send"})).not.toBeInTheDocument();
  expect(screen.getByLabelText("Subject")).toBeDisabled();
 });
});
describe("Portfolio drill-down",()=>{
 const rows:Opportunity[]=[{id:"one",name:"Inactive Test Jail",state:"MA",workflow:"recovery",status:"needs_review",holds:[],signals:["inactivity","product_decline"],prior_cents:10000,current_cents:0,decline_cents:10000,decline_pct:100,change_cents:-10000,prior_tests:10,current_tests:0,partial_decline:false,evidence_quality:"Name & state match",owner:"Test owner",assessment:null,next_action:"Assess opportunity",evidence_hash:"a",last_purchase:"2025-01-01"},{id:"two",name:"Partial Test Jail",state:"NY",workflow:"recovery",status:"awaiting_approval",holds:[],signals:["reduced_purchasing"],prior_cents:20000,current_cents:10000,decline_cents:10000,decline_pct:50,change_cents:-10000,prior_tests:20,current_tests:10,partial_decline:true,evidence_quality:"Alias needs verification",owner:"Other owner",assessment:"pursue",next_action:"Review email",evidence_hash:"b",last_purchase:"2026-09-01"}];
 it("applies KPI deep links and keeps multiple signals on one account row",()=>{
  params.set("signal","inactivity");render(<OpportunityTable rows={rows}/>);
  expect(screen.getByRole("link",{name:/Inactive Test Jail/})).toHaveAttribute("href","/accounts/one");
  expect(screen.queryByRole("link",{name:/Partial Test Jail/})).not.toBeInTheDocument();
  expect(screen.getByText(/1 of 2 accounts/)).toBeInTheDocument();
 });
 it("supports searching and stage filtering without queuing work",()=>{
  render(<OpportunityTable rows={rows}/>);
  fireEvent.change(screen.getByRole("combobox",{name:"Stage filter"}),{target:{value:"awaiting_approval"}});
  expect(screen.getByRole("link",{name:"Review email"})).toHaveAttribute("href","/accounts/two?tab=outreach");
  fireEvent.change(screen.getByLabelText("Search accounts"),{target:{value:"Does not exist"}});
  expect(screen.getByText("No accounts match these filters.")).toBeInTheDocument();
  expect(fetch).not.toHaveBeenCalled();
 });
});
