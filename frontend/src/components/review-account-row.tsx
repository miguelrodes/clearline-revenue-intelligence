import Link from 'next/link';
import {ChevronRight} from 'lucide-react';
import type {ReactNode} from 'react';

type Props = {
 name:string; href:string; sectionId:string; summary:ReactNode; description?:string;
 activity?:ReactNode; expanded:boolean; onToggle:()=>void; disclosure:string; children:ReactNode;
};

export function ReviewAccountRow({name,href,sectionId,summary,description,activity,expanded,onToggle,disclosure,children}:Props) {
 return <article className="check-account">
  <h3 className="review-account-name"><Link href={href}>{name}</Link></h3>
  <p>{summary}</p>
  {description&&<p className="review-organization">{description}</p>}
  {activity}
  <button type="button" className="check-disclosure" aria-expanded={expanded} aria-controls={sectionId} onClick={onToggle}>
   <ChevronRight size={16} aria-hidden="true"/>{disclosure}
  </button>
  <div id={sectionId} hidden={!expanded} className="check-account-content">{expanded&&children}</div>
 </article>;
}
