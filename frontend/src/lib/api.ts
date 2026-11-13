"use client";
import {useEffect,useState,useCallback} from "react";
export async function request<T>(path:string,method="GET",body?:unknown):Promise<T>{
  const response=await fetch(`/api${path}`,{method,cache:"no-store",headers:{"Content-Type":"application/json","X-Clearline-Client":"web"},body:body===undefined?undefined:JSON.stringify(body)});
  if(!response.ok){let message="The local API is unavailable. Check the backend process.";try{const data=await response.json();message=typeof data.detail==="string"?data.detail:JSON.stringify(data.detail||data)}catch{}throw new Error(message)}
  return response.json();
}
export function refresh(){window.dispatchEvent(new Event("clearline-refresh"))}
export function useApi<T>(path:string|null){
 const [data,setData]=useState<T>();const [error,setError]=useState("");
 const reload=useCallback(()=>refresh(),[]);
 useEffect(()=>{let active=true;let busy=false;setData(undefined);setError("");const endpoint=path??"";if(!endpoint)return()=>{active=false};async function load(){if(busy)return;busy=true;try{const value=await request<T>(endpoint);if(active){setData(value);setError("")}}catch(e){if(active)setError((e as Error).message)}finally{busy=false}}
 load();const interval=setInterval(load,5000);window.addEventListener("clearline-refresh",load);return()=>{active=false;clearInterval(interval);window.removeEventListener("clearline-refresh",load)}},[path]);
 return {data,error,reload};
}
export const money=(cents:number=0)=>new Intl.NumberFormat("en-US",{style:"currency",currency:"USD",maximumFractionDigits:0}).format(cents/100);
export const number=(n:number=0)=>new Intl.NumberFormat("en-US").format(n);
export const time=(s?:string|null)=>s?new Date(s).toLocaleString(undefined,{month:"short",day:"numeric",hour:"numeric",minute:"2-digit"}):"—";
const labels:Record<string,string>={internal_investigation:"Investigating internally",human_verification:"Requires verification",monitor:"Monitoring",defer:"Deferred",inactive_recovery:"Inactive customer recovery",purchasing_decline:"Purchasing decline",sku_deterioration:"Product purchasing decline",missed_replenishment:"Missed replenishment window",distributor_recovery:"Distributor purchasing decline",aging_open_order:"Aged open order",cross_sell:"Additional product interest",purchasing_obstacle:"Purchasing obstacle",churn_prevention:"Relationship risk",partial:"Partial purchasing decline",inactivity:"Inactive customers",product_decline:"SKU deterioration",direct_gap_channel_review:"Direct purchase gap",deferred:"Deferred",needs_contact:"Verify contact",no_action:"No action recommended",needs_review:"Awaiting analysis",awaiting_approval:"Approval needed",awaiting_response:"Outreach simulated",approved:"Approved · queued",agent_held:"Agent hold",blocked_config:"Configuration needed",needs_research:"Awaiting research",researched:"Research saved",won:"Order recorded",replied:"Reply recorded"};
export const label=(s:string)=>labels[s]||s.replaceAll("_"," ");
export const signalLabel=(s:string)=>({inactivity:"Inactive",reduced_purchasing:"Purchasing decline",product_decline:"SKU decline",direct_gap_channel_review:"Channel review"}[s]||label(s));
