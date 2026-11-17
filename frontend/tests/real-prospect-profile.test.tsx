import {render, screen, fireEvent, waitFor} from "@testing-library/react";
import {it, expect, vi} from "vitest";
import {RealProspectProfile} from "../src/components/real-prospect-profile";
import type {Account, Draft} from "../src/lib/types";

const draft: Draft = {
  id: "saved-discovery-email", opportunity_id: "real-prospect", version: 2,
  evidence_hash: "snapshot", status: "awaiting_approval", can_review: true,
  recipient: "simulation@example.invalid", subject: "Technical discovery",
  analysis: {recipient: "purchasing@example.org"},
  body: "Which office evaluates screening products?", created_at: "2026-11-01",
};
const prospect: Account = {
  id: "real-prospect", name: "Pennsylvania Department of Corrections", status: "awaiting_approval",
  workflow: "prospecting", state: "PA", holds: [], decline_cents: 0, evidence_hash: "snapshot",
  evidence: {profile: {official_url: "https://www.pa.gov", selection_reason: "Documented mail screening incident."}},
  jobs: [], events: [], drafts: [draft], outbox: [], outcomes: [], assessment: null, trends: null,
};

it("opens the saved real prospect email and requires confirmation of the exact version", async () => {
  const fetch = vi.fn().mockResolvedValue({ok: true, json: async () => ({status: "approved"})});
  vi.stubGlobal("fetch", fetch);
  window.history.replaceState(null, "", "#prospect-outreach");
  try {
    render(<RealProspectProfile account={{...prospect, prospect_contact_required: false}}/>);
    expect(screen.getByRole("region", {name: "Prospect outreach"})).toHaveFocus();
    expect(screen.getByLabelText("Subject")).toHaveValue(draft.subject);
    fireEvent.click(screen.getByRole("button", {name: "Approve simulated send"}));
    expect(fetch).not.toHaveBeenCalled();
    const recipients = document.querySelector("dialog dl");
    expect(recipients?.querySelectorAll("div")[0]).toHaveTextContent("Intended purchasing contactpurchasing@example.org");
    expect(recipients?.querySelectorAll("div")[1]).toHaveTextContent("Simulated delivery destinationsimulation@example.invalid");
    fireEvent.click(screen.getByRole("button", {name: "Confirm"}));
    await waitFor(() => expect(fetch).toHaveBeenCalledOnce());
    const [url, options] = fetch.mock.calls[0];
    expect(url).toBe(`/api/drafts/${draft.id}/decision`);
    expect(JSON.parse(options.body)).toEqual({
      version: 2, subject: draft.subject, recipient: draft.recipient, body: draft.body, approve: true,
    });
  } finally {
    window.history.replaceState(null, "", "/");
    vi.unstubAllGlobals();
  }
});

it("reflects a changed approval state without offering a second send", () => {
  const view = render(<RealProspectProfile account={prospect}/>);
  view.rerender(<RealProspectProfile account={{...prospect, status: "approved",
    drafts: [{...draft, status: "approved", can_review: false}]}}/>);
  expect(screen.queryByRole("button", {name: "Approve simulated send"})).toBeNull();
  expect(screen.getByText("The approved email is queued for simulated delivery.")).toBeVisible();
  view.rerender(<RealProspectProfile account={{...prospect, drafts: [{...draft, can_review: false}]}}/>);
  expect(screen.queryByRole("button", {name: "Approve simulated send"})).toBeNull();
});

it("shows a preliminary prospect without offering qualification or outreach", () => {
  render(<RealProspectProfile account={{...prospect, name: "Massachusetts Department of Correction",
    status: "needs_research", drafts: []}}/>);
  expect(screen.getByText("No completed research is saved for this prospect.")).toBeVisible();
  expect(screen.queryByRole("region", {name: "Prospect outreach"})).toBeNull();
  expect(screen.queryByText(/start one from the account header/i)).toBeNull();
});

it('shows the actual verification step beside the blocked real draft',()=>{
  render(<RealProspectProfile account={{...prospect,prospect_contact_required:true,drafts:[{...draft,can_review:false,can_edit:false}]}}/>);
  expect(screen.getByRole('link',{name:'Verify contact and route'}).getAttribute('href')).toBe('/screening?candidate='+prospect.id+'#prospect-permission');
  expect(screen.queryByRole('button',{name:'Approve simulated send'})).toBeNull();
});

it('shows the latest approval with its draft version and a return link to the delivery queue',()=>{
 render(<RealProspectProfile account={{...prospect,status:'approved',drafts:[{...draft,status:'approved',can_review:false}],
   prospect_progress:{stage:'awaiting_delivery',next_action:'The approved email is queued for simulated delivery.',
    latest_activity:{label:'Email approved',at:'2026-11-17T01:28:01Z'}}}}/>);
 expect(screen.getByText('Approved · awaiting simulated delivery')).toBeVisible();
 expect(screen.getByText(/Latest action: Email approved/)).toHaveTextContent('Draft v2');
 expect(screen.getByRole('link',{name:'View in candidate pipeline'})).toHaveAttribute('href','/screening?stage=awaiting_delivery&q=Pennsylvania+Department+of+Corrections#candidates');
 expect(screen.queryByRole('button',{name:'Approve simulated send'})).toBeNull();
});
