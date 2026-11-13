import Link from 'next/link';
import type {ReactNode} from 'react';
import {money} from '@/lib/api';

type Props={
 title:string;
 description:string;
 href:string;
 buttonLabel:string;
 ariaLabel?:string;
 financialCents?:number|null;
 financialLabel?:string;
 financialEmptyLabel?:string;
 scopeLabel?:string;
 children?:ReactNode;
};

/** Shared, compact action row used by Overview and Opportunity Signal details. */
export function RecommendedActionRow({title,description,href,buttonLabel,ariaLabel,financialCents,financialLabel,financialEmptyLabel,scopeLabel,children}:Props){
 return <div className="brief-action-main">
  <div className="brief-action-body">
   <h3>{title}</h3>
   <p>{description}</p>
   <div className="brief-financial">
    {financialCents!=null&&financialCents>0?<span><strong>{money(financialCents)}</strong> <span>{financialLabel||'associated historical decline'}</span></span>:financialEmptyLabel?<span>{financialEmptyLabel}</span>:null}
    {scopeLabel&&<small>{scopeLabel}</small>}
   </div>
   {children}
  </div>
  <Link href={href} className="action-link" aria-label={ariaLabel||title}>{buttonLabel} →</Link>
 </div>;
}
