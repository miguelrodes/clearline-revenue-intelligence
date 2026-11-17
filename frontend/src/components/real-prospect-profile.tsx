"use client";

import Link from "next/link";
import {useEffect, useRef} from "react";
import type {Account} from "@/lib/types";
import {label} from "@/lib/api";
import {DraftEditor, ResearchView} from "./detail-views";
import {StatusBadge} from "./status-badge";
import {ProspectActivity} from "./prospect-activity";
import {display} from "@/lib/prospect-pipeline";

export function RealProspectProfile({account}: {account: Account}) {
  const profile = useRef<HTMLDivElement>(null);
  const draft = account.drafts[0];
  const progress=account.prospect_progress;
  const reviewing = account.status === "awaiting_approval" && draft?.status === "awaiting_approval";

  useEffect(() => {
    // The account loads asynchronously, after the browser first sees the fragment.
    const anchor = window.location.hash.slice(1);
    if (anchor !== "prospect-outreach" && anchor !== "prospect-research") return;
    const section = profile.current?.querySelector<HTMLElement>(`#${anchor}`);
    const review = anchor === "prospect-outreach" && section?.querySelector<HTMLDetailsElement>(".next-action-draft");
    if (review) review.open = true;
    section?.focus({preventScroll: true});
    section?.scrollIntoView?.({block: "start"});
  }, [account.id]);

  return <div ref={profile} className="account-profile">
    <div className="page-head"><h1>{account.name}</h1><StatusBadge value={account.prospect_contact_required ? "needs_verification" : account.status} text={progress&&display(progress.stage)}/></div>
    <p>Real SwabTek prospect. Its customer relationship and buying intent are unverified.</p>
    {progress&&<><ProspectActivity activity={progress.latest_activity} version={draft?.version}/>
      <p>{progress.next_action}</p>
      <Link className="action-link" href={'/screening?'+new URLSearchParams({stage:progress.stage,q:account.name})+'#candidates'}>View in candidate pipeline</Link>
    </>}
    {draft && <section id="prospect-outreach" aria-label="Prospect outreach" tabIndex={-1}>
      {reviewing && (draft.can_review || draft.can_edit)
        ? <div className="account-section"><h2>Next Action</h2>
            <DraftEditor key={account.id} draft={draft} prospectContactVerified={account.prospect_contact_required === false} inlineReview/>
          </div>
        : <div className="account-section">
            <h2>Prospect outreach</h2>
            {account.prospect_contact_required ? <p><Link className="action-link" href={`/screening?candidate=${encodeURIComponent(account.id)}#prospect-permission`}>Verify contact and route</Link></p>
              : progress ? null : account.status === "approved" ? <p>The approved email is queued for simulated delivery.</p>
              : account.status === "awaiting_response" && account.outbox.length > 0 ? <p>The simulated delivery is recorded. Awaiting a response.</p>
              : <p>Draft status: {label(draft.status)}. This version is unavailable for approval.</p>}
            <details><summary>Read version {draft.version} · {draft.subject}</summary>
              <p>{draft.recipient}</p><p className="email-copy">{draft.body}</p>
            </details>
          </div>}
    </section>}
    <section id="prospect-research" aria-label="Saved prospect evidence" tabIndex={-1}>
      <ResearchView account={account}/>
    </section>
  </div>;
}
