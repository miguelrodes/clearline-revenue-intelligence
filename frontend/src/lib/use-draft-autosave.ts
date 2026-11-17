"use client";
import {useCallback,useEffect,useRef,useState} from 'react';
import {request,refresh} from './api';
import type {Draft} from './types';

type Fields=Pick<Draft,'recipient'|'subject'|'body'>;
type Snapshot=Fields & Pick<Draft,'id'|'version'>;
function copy(d:Fields):Fields{return {recipient:d.recipient,subject:d.subject,body:d.body}}
function same(a:Fields,b:Fields){return a.recipient===b.recipient&&a.subject===b.subject&&a.body===b.body}

export function useDraftAutosave(d:Draft,editable=true){
 const [fields,setFields]=useState<Fields>(()=>copy(d));
 const [saving,setSaving]=useState(false),[error,setError]=useState('');
 const saved=useRef<Snapshot>(d),remoteId=useRef(d.id);
 const inFlight=useRef<Promise<Snapshot>|null>(null);
 const conflict=useRef(false),generation=useRef(0);
 const dirty=!same(fields,d);
 const valid=Object.values(fields).every(v=>v.trim());
 useEffect(()=>{
  if(remoteId.current===d.id)return;
  remoteId.current=d.id;
  if(d.id===saved.current.id || d.version<saved.current.version)return;
  generation.current++;
  if(same(fields,saved.current)){saved.current=d;setFields(copy(d));conflict.current=false;setError('')}
  else{conflict.current=true;setError('This email changed elsewhere. Reopen it before editing.')}
 },[d,fields]);
 const save=useCallback(async(values:Fields,expected=generation.current):Promise<Snapshot>=>{
  while(inFlight.current)await inFlight.current;
  if(conflict.current||expected!==generation.current)throw new Error('This email changed elsewhere. Reopen it before editing.');
  const base=saved.current;
  if(same(values,base))return base;
  if(!editable||!Object.values(values).every(v=>v.trim()))throw new Error('Complete all email fields before confirming.');
  const pending=request<{draft_id:string;version:number}>(`/drafts/${base.id}`,'PATCH',{version:base.version,...values}).then(result=>{
   const next={id:result.draft_id,version:result.version,...values};
   saved.current=next;
   refresh();
   return next;
  });
  inFlight.current=pending;setSaving(true);
  try{return await pending}
  catch(e){setError((e as Error).message);throw e}
  finally{inFlight.current=null;setSaving(false)}
 },[editable]);
 useEffect(()=>{
  if(!editable||!dirty||!valid||error||saving||same(fields,saved.current))return;
  const timer=setTimeout(()=>{void save(fields).catch(()=>{})},650);
  return()=>clearTimeout(timer);
 },[fields,dirty,valid,editable,saving,error,save]);
 useEffect(()=>{
  if(!dirty&&!saving)return;
  const warn=(e:BeforeUnloadEvent)=>{e.preventDefault();e.returnValue=''};
  window.addEventListener('beforeunload',warn);return()=>window.removeEventListener('beforeunload',warn)
 },[dirty,saving]);
 return {fields,setFields,saving,error,pending:dirty||saving,valid,save,generation,
  status:error?'Could not save edits.':saving||dirty?(valid?'Saving…':'Complete all fields to save.'):'Saved',
  retry:()=>{if(!conflict.current)setError('')}};
}
