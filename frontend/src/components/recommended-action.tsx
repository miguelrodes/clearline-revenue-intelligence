'use client';
import Link from 'next/link';
import {useEffect,useLayoutEffect,useRef,type ReactNode} from 'react';
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


export function RecommendedActionList({children,label,rowsKey,sort}:{children:ReactNode;label:string;rowsKey:string;sort?:string}) {
 const ref=useRef<HTMLOListElement>(null);
 useLayoutEffect(()=>{
  const list=ref.current;
  if(!list)return;
  const rows=Array.from(list.querySelectorAll<HTMLElement>(':scope > li > .brief-action-main'));
  const measure=()=>{
   const sizes=rows.slice(0,4).map(row=>row.getBoundingClientRect().height-
    (row.querySelector('details[open] .brief-member-list')?.getBoundingClientRect().height||0));
   // Size the list before the page scrolls to sections beneath it.
   list.style.maxHeight=sizes.length===4?`${sizes[0]+sizes[1]+sizes[2]+sizes[3]/2}px`:'';
  };
  measure();
  if(typeof ResizeObserver==='undefined')return;
  const observer=new ResizeObserver(measure);
  observer.observe(list);
  rows.forEach(row=>observer.observe(row));
  return ()=>observer.disconnect();
 },[rowsKey]);
 useEffect(()=>{if(sort)ref.current?.scrollTo?.({top:0,behavior:'smooth'})},[sort]);
 return <ol ref={ref} className="brief-actions" aria-label={label} tabIndex={0}>{children}</ol>;
}
