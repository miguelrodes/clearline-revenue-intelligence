"use client";
import {useEffect,useState,useCallback} from "react";
export async function request<T>(path:string,method="GET",body?:unknown):Promise<T>{
  const response=await fetch(`/api${path}`,{method,cache:"no-store",headers:{"Content-Type":"application/json","X-Clearline-Client":"web"},body:body===undefined?undefined:JSON.stringify(body)});
  if(!response.ok){let message="The local API is unavailable. Check the backend process.";try{const data=await response.json();message=typeof data.detail==="string"?data.detail:JSON.stringify(data.detail||data)}catch{}throw new Error(message)}
  return response.json();
}
export function refresh(){window.dispatchEvent(new Event("clearline-refresh"))}
type ReadState = {data?:unknown; error:string};
type Listener = (state:ReadState)=>void;

// Each mounted endpoint owns one poll timer. Dispose its results with its last reader.
function sharedRead(path:string){
 const listeners=new Set<Listener>();
 let state:ReadState={error:""}, busy=false, invalidated=false;
 async function load(){
  if(busy)return;
  busy=true;
  try{
   const data=await request(path);
   if(!invalidated)state={data,error:""};
  }catch(e){
   if(!invalidated)state={...state,error:(e as Error).message};
  }finally{
   busy=false;
   if(listeners.size){
    if(invalidated){invalidated=false;void load()}
    else listeners.forEach(listener=>listener(state));
   }
  }
 }
 function invalidate(){if(busy)invalidated=true;else void load()}
 const timer=window.setInterval(load,5000);
 window.addEventListener("clearline-refresh",invalidate);
 return function subscribe(listener:Listener){
  listeners.add(listener);listener(state);
  if(listeners.size===1)void load();
  return ()=>{
   listeners.delete(listener);
   if(!listeners.size){
    window.clearInterval(timer);
    window.removeEventListener("clearline-refresh",invalidate);
    readers.delete(path);
   }
  };
 };
}
const readers=new Map<string,ReturnType<typeof sharedRead>>();
export function useApi<T>(path:string|null){
 const [state,setState]=useState<ReadState & {path:string}>({path:"",error:""});
 const reload=useCallback(()=>refresh(),[]);
 useEffect(()=>{
  if(!path)return;
  const subscribe=readers.get(path)??sharedRead(path);
  readers.set(path,subscribe);
  return subscribe(value=>setState({...value,path}));
 },[path]);
 return {data:state.path===path?state.data as T|undefined:undefined,error:state.path===path?state.error:"",reload};
}
export const money=(cents:number=0)=>new Intl.NumberFormat("en-US",{style:"currency",currency:"USD",maximumFractionDigits:0}).format(cents/100);
export const number=(n:number=0)=>new Intl.NumberFormat("en-US").format(n);
export const time=(s?:string|null)=>s?new Date(s).toLocaleString(undefined,{month:"short",day:"numeric",hour:"numeric",minute:"2-digit"}):"—";
const labels:Record<string,string>={opted_out:"Do Not Contact",recipient_opted_out:"Recipient opted out",outreach_paused:"Outreach paused",analyzing_reply:"Reviewing customer reply",internal_investigation:"Investigating internally",human_verification:"Requires verification",monitor:"Monitoring",defer:"Deferred",inactive_recovery:"Inactive customer recovery",purchasing_decline:"Purchasing decline",sku_deterioration:"Product purchasing decline",missed_replenishment:"Missed replenishment window",distributor_recovery:"Distributor purchasing decline",aging_open_order:"Aged open order",cross_sell:"Additional product interest",purchasing_obstacle:"Purchasing obstacle",churn_prevention:"Relationship risk",partial:"Partial purchasing decline",inactivity:"Inactive customers",product_decline:"SKU deterioration",direct_gap_channel_review:"Direct purchase gap",deferred:"Deferred",needs_contact:"Verify contact",no_action:"No action recommended",needs_review:"Awaiting analysis",awaiting_approval:"Approval needed",awaiting_response:"Awaiting customer response",approved:"Approved · queued",agent_held:"Agent hold",blocked_config:"Configuration needed",needs_research:"Awaiting research",researched:"Research saved",won:"Order recorded",replied:"Reply recorded"};
export const label=(s:string)=>labels[s]||s.replaceAll("_"," ");
export const signalLabel=(s:string)=>({inactivity:"Inactive",reduced_purchasing:"Purchasing decline",product_decline:"SKU decline",direct_gap_channel_review:"Channel review"}[s]||label(s));
