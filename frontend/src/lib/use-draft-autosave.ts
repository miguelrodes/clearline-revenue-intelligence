"use client";
import {useEffect,useRef,useState} from 'react';
import {request,refresh} from './api';
import type {Draft} from './types';
export function useDraftAutosave(d:Draft,editable=true){
 const [fields,setFields]=useState({recipient:d.recipient,subject:d.subject,body:d.body});
 const [saving,setSaving]=useState(false);const [error,setError]=useState('');const [retry,setRetry]=useState(0);
 const waiting=useRef<string|null>(null);const known=useRef(d.id);
 const dirty=fields.recipient!==d.recipient||fields.subject!==d.subject||fields.body!==d.body;
 const valid=Object.values(fields).every(v=>v.trim());
 useEffect(()=>{if(known.current!==d.id){known.current=d.id;if(!dirty||waiting.current===d.id){setFields({recipient:d.recipient,subject:d.subject,body:d.body});waiting.current=null;setSaving(false);setError('')}else{setSaving(false);setError('This email changed elsewhere. Reopen it before editing.')}}},[d.id,d.recipient,d.subject,d.body,dirty]);
 useEffect(()=>{if(!editable||!dirty||!valid||saving||error)return;
  const timer=setTimeout(async()=>{setSaving(true);try{const result=await request<{draft_id:string}>(`/drafts/${d.id}`,'PATCH',{version:d.version,...fields});waiting.current=result.draft_id;refresh()}catch(e){setError((e as Error).message);setSaving(false)}},650);
  return()=>clearTimeout(timer);
 },[fields,d.id,d.version,dirty,valid,editable,saving,error,retry]);
 useEffect(()=>{if(!dirty&&!saving)return;const warn=(e:BeforeUnloadEvent)=>{e.preventDefault();e.returnValue=''};window.addEventListener('beforeunload',warn);return()=>window.removeEventListener('beforeunload',warn)},[dirty,saving]);
 return {fields,setFields,saving,error,pending:dirty||saving,status:error?'Could not save edits.':saving?'Saving…':dirty?(valid?'Saving…':'Complete all fields to save.'):'Saved',retry:()=>{setError('');setRetry(n=>n+1)}};
}
