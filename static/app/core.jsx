// ─── core.jsx ────────────────────────────────────────────────────────────────
// API client, helpers, icons and the small shared building blocks every page uses.
const {useState,useEffect,useRef,useMemo,useCallback,useContext,createContext}=React;

// ─── API ──────────────────────────────────────────────────────────────────────
function token(){try{return localStorage.getItem("sp_token")||"";}catch(e){return "";}}
// Last response of each GET, so a page you come back to can show its previous
// data immediately and refresh quietly, instead of flashing empty/skeleton.
const _getCache=new Map();
function peek(path,fallback){return _getCache.has(path)?_getCache.get(path):fallback;}
function clearGetCache(){_getCache.clear();}
// Numbers count up like the prototype. Starts from 0 whenever `replay`
// changes (page opened, filter changed); a background refresh just eases
// from the old number to the new one.
function useCountUp(target,ms=900,replay){
  const [v,setV]=useState(0);const cur=useRef(0);const lastReplay=useRef(undefined);
  useEffect(()=>{
    if(target==null)return;
    const from=lastReplay.current===replay?cur.current:0;lastReplay.current=replay;
    let raf;const t0=performance.now();
    const tick=now=>{const p=Math.min(1,(now-t0)/ms);const val=from+(target-from)*(1-Math.pow(1-p,3));cur.current=val;setV(val);if(p<1)raf=requestAnimationFrame(tick);};
    raf=requestAnimationFrame(tick);return()=>cancelAnimationFrame(raf);
  },[target,replay]);
  return target==null?null:v;
}
function CountUp({value,replay,format}){
  const v=useCountUp(value,900,replay);
  if(v==null)return "—";
  return format?format(v):Math.round(v).toLocaleString();
}
async function req(method,path,body){
  const opts={method,headers:{"Content-Type":"application/json",...(token()?{Authorization:`Bearer ${token()}`}:{})}};
  if(body!==undefined)opts.body=JSON.stringify(body);
  const res=await fetch(path,opts);
  // Session expired or belongs to someone else → back to the sign-in page.
  if(res.status===401&&token()&&path!=="/auth/login"){
    try{localStorage.removeItem("sp_token");}catch(e){}
    _getCache.clear();window.location.reload();
    return new Promise(()=>{});
  }
  if(!res.ok){
    const e=await res.json().catch(()=>({detail:res.statusText}));
    let msg=e.detail||"Request failed";
    if(Array.isArray(msg))msg=msg.map(d=>d.msg||JSON.stringify(d)).join("; ");
    else if(typeof msg!=="string")msg=JSON.stringify(msg);
    throw new Error(msg);
  }
  if(res.status===204)return null;
  const data=await res.json();
  if(method==="GET")_getCache.set(path,data);
  return data;
}
const api={
  req,
  login:(sam)=>req("POST","/auth/login",{sam_account_name:sam}),
  gsConfig:()=>fetch("/auth/gs_config").then(r=>r.json()),
  devMode:()=>fetch("/auth/dev_mode").then(r=>r.json()),
  getMe:()=>req("GET","/auth/me"),
  summary:(jt)=>req("GET",`/summary/stats?job_type=${jt||"all"}`),
  analytics:(period,jt)=>req("GET",`/analytics/runs?period=${period}&job_type=${jt||"all"}`),
  // dashboards
  getDashboards:()=>req("GET","/dashboards/"),
  createDashboard:(b)=>req("POST","/dashboards/",b),
  updateDashboard:(id,b)=>req("PUT",`/dashboards/${id}`,b),
  deleteDashboard:(id)=>req("DELETE",`/dashboards/${id}`),
  runDashboardNow:(id,b)=>req("POST",`/dashboards/${id}/run`,b),
  searchTableauViews:(q)=>req("GET",`/dashboards/search/views?q=${encodeURIComponent(q)}`),
  pauseDashboardSchedules:(id)=>req("POST",`/dashboards/${id}/pause_schedules`),
  // scripts
  getScripts:()=>req("GET","/scripts/"),
  createScript:(b)=>req("POST","/scripts/",b),
  updateScript:(id,b)=>req("PUT",`/scripts/${id}`,b),
  deleteScript:(id)=>req("DELETE",`/scripts/${id}`),
  runScript:(id,email)=>req("POST",`/scripts/${id}/run?triggered_by=${encodeURIComponent(email||"")}`),
  stopScript:(id)=>req("POST",`/scripts/${id}/stop`),
  pauseScriptSchedules:(id)=>req("POST",`/scripts/${id}/pause_schedules`),
  latestLog:(id)=>req("GET",`/scripts/${id}/logs/latest`),
  checkUpload:(name)=>req("GET",`/scripts/upload/check?script_name=${encodeURIComponent(name)}`),
  registerScript:(fd)=>{const t=token();return fetch("/scripts/register",{method:"POST",headers:t?{Authorization:`Bearer ${t}`}:{},body:fd}).then(async r=>{if(!r.ok){const e=await r.json().catch(()=>({detail:r.statusText}));throw new Error(typeof e.detail==="string"?e.detail:"Upload failed");}return r.json();});},
  // schedules
  getSchedules:(t)=>req("GET",`/schedules/${t&&t!=="all"?"?schedule_type="+t:""}`),
  createScriptSchedule:(b)=>req("POST","/schedules/script",b),
  updateScriptSchedule:(id,b)=>req("PUT",`/schedules/script/${id}`,b),
  createTableauSchedule:(b)=>req("POST","/schedules/tableau",b),
  updateTableauSchedule:(id,b)=>req("PUT",`/schedules/tableau/${id}`,b),
  createSpSchedule:(b)=>req("POST","/schedules/sharepoint",b),
  updateSpSchedule:(id,b)=>req("PUT",`/schedules/sharepoint/${id}`,b),
  toggleSchedule:(id)=>req("PATCH",`/schedules/${id}/toggle`),
  runScheduleNow:(id)=>req("POST",`/schedules/${id}/run_now`),
  deleteSchedule:(id)=>req("DELETE",`/schedules/${id}`),
  getShares:(id)=>req("GET",`/schedules/${id}/shares`),
  addShare:(id,user_id,access)=>req("POST",`/schedules/${id}/shares`,{user_id,access}),
  changeShare:(id,uid,access)=>req("PATCH",`/schedules/${id}/shares/${uid}`,{access}),
  removeShare:(id,uid)=>req("DELETE",`/schedules/${id}/shares/${uid}`),
  // logs
  getLogs:(p)=>req("GET","/logs/?"+new URLSearchParams(p||{})),
  logCounts:(p)=>req("GET","/logs/counts?"+new URLSearchParams(p||{})),
  logHeatmap:(p)=>req("GET","/logs/heatmap?"+new URLSearchParams(p||{})),
  appVersion:()=>req("GET","/api/version"),
  changelog:()=>req("GET","/api/changelog"),
  getLog:(id)=>req("GET",`/logs/${id}`),
  getRunning:()=>req("GET","/logs/running"),
  stopLog:(id)=>req("POST",`/logs/${id}/stop`),
  // users
  getUsers:()=>req("GET","/users/"),
  searchUsers:(q)=>req("GET",`/users/search?q=${encodeURIComponent(q)}`),
  updateUser:(id,b)=>req("PUT",`/users/${id}`,b),
  deleteUser:(id)=>req("DELETE",`/users/${id}`),
  // feedback
  getFeedback:()=>req("GET","/feedback/"),
  createFeedback:(b,uid)=>req("POST",`/feedback/?user_id=${uid||""}`,b),
  updateFeedback:(id,s)=>req("PATCH",`/feedback/${id}`,{status:s}),
  deleteFeedback:(id)=>req("DELETE",`/feedback/${id}`),
  voteFeedback:(id)=>req("POST",`/feedback/${id}/vote`),
  editFeedback:(id,b)=>req("PUT",`/feedback/${id}`,b),
  editComment:(cid,message)=>req("PUT",`/feedback/comments/${cid}`,{message}),
  getComments:(id)=>req("GET",`/feedback/${id}/comments`),
  addComment:(id,message)=>req("POST",`/feedback/${id}/comments`,{message}),
  deleteComment:(cid)=>req("DELETE",`/feedback/comments/${cid}`),
  voteComment:(cid)=>req("POST",`/feedback/comments/${cid}/vote`),
  // sharepoint sites
  getSpSites:()=>req("GET","/sharepoint/sites/"),
  createSpSite:(b)=>req("POST","/sharepoint/sites/",b),
  updateSpSite:(id,b)=>req("PUT",`/sharepoint/sites/${id}`,b),
  deleteSpSite:(id)=>req("DELETE",`/sharepoint/sites/${id}`),
  testSpSite:(id)=>req("POST",`/sharepoint/sites/${id}/test`),
  spSiteActivity:(id)=>req("GET",`/sharepoint/sites/${id}/activity`),
};

// ─── Time & number helpers (all display in Pacific time, as before) ──────────
const TZ="America/Los_Angeles";
function toDate(d){if(!d)return null;if(d instanceof Date)return d;const s=typeof d==="string"&&!/[zZ]|[+-]\d\d:?\d\d$/.test(d)?d+"Z":d;return new Date(s);}
// "Needs attention" = active schedules whose most recent run failed (any date).
// A schedule drops off by itself as soon as its next run succeeds.
const isFailing=s=>!!s&&s.is_active&&(s.last_run_status==="failed"||s.last_run_status==="partial")&&!(s.name||"").startsWith("[Ad-hoc]");
function msStr(ms){if(!ms)return"—";const s=Math.round(ms/1000),m=Math.floor(s/60),h=Math.floor(m/60);if(h>0)return`${h}h ${m%60}m`;if(m>0)return`${m}m ${String(s%60).padStart(2,"0")}s`;return`${s}s`;}
function secStr(sec){if(sec==null)return"No limit";const h=Math.floor(sec/3600),m=Math.floor(sec%3600/60);if(h&&m)return`${h}h ${m}m`;if(h)return`${h} hour${h>1?"s":""}`;return`${m} min`;}
function fmtDate(d){const x=toDate(d);if(!x)return"—";return x.toLocaleString("en-US",{month:"short",day:"numeric",year:"numeric",hour:"numeric",minute:"2-digit",hour12:true,timeZone:TZ});}
function fmtDateShort(d){const x=toDate(d);if(!x)return"—";return x.toLocaleDateString("en-US",{month:"short",day:"numeric",year:"numeric",timeZone:TZ});}
function fmtClock(d){const x=toDate(d);if(!x)return"—";return x.toLocaleTimeString("en-US",{hour:"numeric",minute:"2-digit",hour12:true,timeZone:TZ});}
function dayKey(d){const x=toDate(d);return x?x.toLocaleDateString("en-CA",{timeZone:TZ}):"";}
function fmtWhen(d){
  const x=toDate(d);if(!x)return"—";
  const today=dayKey(new Date()),k=dayKey(x);
  const y=new Date();y.setDate(y.getDate()-1);const t=new Date();t.setDate(t.getDate()+1);
  if(k===today)return"Today "+fmtClock(x);
  if(k===dayKey(y))return"Yesterday "+fmtClock(x);
  if(k===dayKey(t))return"Tomorrow "+fmtClock(x);
  return x.toLocaleString("en-US",{month:"short",day:"numeric",hour:"numeric",minute:"2-digit",hour12:true,timeZone:TZ});
}
function fmtTime(t){if(!t)return"—";const[h,m]=t.split(":").map(Number);const ampm=h>=12?"PM":"AM";const h12=h%12||12;return`${h12}:${String(m).padStart(2,"0")} ${ampm}`;}
function relAgo(d){const x=toDate(d);if(!x)return"";const s=Math.max(0,(Date.now()-x.getTime())/1000);if(s<60)return"just now";if(s<3600)return`${Math.floor(s/60)}m ago`;if(s<86400)return`${Math.floor(s/3600)}h ago`;return`${Math.floor(s/86400)}d ago`;}
function todayStr(){return dayKey(new Date());}
function addDays(ymd,n){const d=new Date(ymd+"T12:00:00");d.setDate(d.getDate()+n);return d.toISOString().slice(0,10);}
function nameToInitials(name=""){const p=(name||"").trim().split(/\s+/).filter(Boolean);if(p.length>=2)return(p[0][0]+p[p.length-1][0]).toUpperCase();return((name||"").slice(0,2)||"?").toUpperCase();}
function splitEmails(s){return(s||"").split(/[;,]/).map(x=>x.trim()).filter(Boolean);}
function lsGet(k,d){try{const v=localStorage.getItem(k);return v==null?d:v;}catch(e){return d;}}
function lsSet(k,v){try{localStorage.setItem(k,v);}catch(e){}}

// ─── App version ──────────────────────────────────────────────────────────────
// Date-based, like WayPOINT. Keep equal to __version__ in main.py and the ?v= in index.html.
const UI_VERSION="2026.11.06";
// "2026.11.06.2" -> compares part by part (a missing part counts as 0)
const verParts=v=>String(v||"").split(".").map(x=>parseInt(x,10)||0);
function verCmp(a,b){const A=verParts(a),B=verParts(b);for(let i=0;i<Math.max(A.length,B.length);i++){const d=(A[i]||0)-(B[i]||0);if(d)return d<0?-1:1;}return 0;}
// CHANGELOG.md -> headings and bullet lists (supports **bold**, *italic*, `code`; indented lines continue a bullet)
function mdInline(t,key){
  const parts=[];let rest=String(t);let i=0;const re=/\*\*(.+?)\*\*|`(.+?)`|\*(.+?)\*/;
  while(rest){const m=rest.match(re);if(!m){parts.push(rest);break;}
    if(m.index)parts.push(rest.slice(0,m.index));
    parts.push(m[1]!=null?<b key={key+"-"+i++}>{m[1]}</b>:m[2]!=null?<code key={key+"-"+i++}>{m[2]}</code>:<i key={key+"-"+i++}>{m[3]}</i>);
    rest=rest.slice(m.index+m[0].length);}
  return parts;
}
function Changelog({text}){
  const blocks=[];let list=null;let item=null;
  const flush=()=>{if(list){blocks.push({ul:list});list=null;item=null;}};
  String(text||"").split("\n").forEach(l=>{
    if(/^##\s+/.test(l)){flush();blocks.push({h:l.replace(/^##\s+/,"")});return;}
    if(/^#\s+/.test(l))return;                                   // the file's own title
    const m=l.match(/^(\s*)-\s+(.*)$/);
    if(m){if(!list)list=[];const depth=m[1].length>=2?1:0;item={text:m[2],depth};list.push(item);return;}
    if(/^\s{2,}\S/.test(l)&&item){item.text+=" "+l.trim();return;}
    if(!l.trim())return;
    flush();blocks.push({p:l.trim()});
  });
  flush();
  if(!blocks.length)return <div className="muted small">No change list yet.</div>;
  let firstH=true;
  return <div className="changelog">{blocks.map((b,i)=>{
    if(b.h){const cur=firstH;firstH=false;const v=b.h.trim();
      return <h3 key={i}>{mdInline(v,"h"+i)}{cur&&verCmp(v,UI_VERSION)===0&&<span className="cl-cur">You're on this</span>}</h3>;}
    if(b.p)return <p key={i}>{mdInline(b.p,"p"+i)}</p>;
    return <ul key={i}>{b.ul.map((it,j)=><li key={j} className={it.depth?"sub":undefined}>{mdInline(it.text,"l"+i+"-"+j)}</li>)}</ul>;
  })}</div>;
}
function WhatsNewModal({onClose}){
  const [data,setData]=useState(null);const [err,setErr]=useState("");
  useEffect(()=>{api.changelog().then(setData).catch(e=>setErr(e.message));},[]);
  return <Modal title="What's new" sub={`You are on Conductor ${data?.version||UI_VERSION}`} onClose={onClose} width={620} closeOnOverlay>
    {err?<div className="muted small">Could not load: {err}</div>:!data?<div className="muted small" style={{display:"flex",gap:8,alignItems:"center"}}><Spinner size={12}/>Loading…</div>:<Changelog text={data.text}/>}
  </Modal>;
}

// ─── "New" shared schedules ───────────────────────────────────────────────────
// A schedule someone shared with you counts as new until you open it (or dismiss
// the banner). Remembered per person in this browser. The first time on a browser,
// only shares from the last 7 days count as new.
function seenSharesKey(u){return "cond_seen_shares_"+(u?.id||"");}
const shareKey=s=>`${s.id}@${s.shared_at||""}`;   // re-sharing later makes it new again
function newSharedSchedules(u,schedules){
  if(!u)return [];
  let seen=null;try{seen=JSON.parse(localStorage.getItem(seenSharesKey(u))||"null");}catch(e){seen=null;}
  const shared=(schedules||[]).filter(s=>(s.my_access==="edit"||s.my_access==="view")&&s.shared_at);
  if(!seen){seen={};const cut=Date.now()-7*86400e3;shared.forEach(s=>{if(toDate(s.shared_at).getTime()<cut)seen[shareKey(s)]=1;});
    try{localStorage.setItem(seenSharesKey(u),JSON.stringify(seen));}catch(e){}}
  return shared.filter(s=>!seen[shareKey(s)]);
}
function markSharesSeen(u,list){
  if(!u||!list||!list.length)return;let seen={};
  try{seen=JSON.parse(localStorage.getItem(seenSharesKey(u))||"{}")||{};}catch(e){}
  list.forEach(s=>{seen[shareKey(s)]=1;});
  try{localStorage.setItem(seenSharesKey(u),JSON.stringify(seen));}catch(e){}
  window.dispatchEvent(new Event("cond-shares-changed"));
}
const isAdminUser=u=>["admin","Admin"].includes(u?.role);

// ─── App context (current user, navigation, toasts, confirm, running jobs) ───
const AppCtx=createContext(null);
const useApp=()=>useContext(AppCtx);

function useInterval(fn,ms,deps=[]){
  const ref=useRef(fn);ref.current=fn;
  useEffect(()=>{if(!ms)return;const t=setInterval(()=>ref.current(),ms);return()=>clearInterval(t);},[ms,...deps]);
}
function useOutside(ref,onOut,active=true){
  useEffect(()=>{
    if(!active)return;
    const h=e=>{if(ref.current&&!ref.current.contains(e.target))onOut();};
    document.addEventListener("mousedown",h);return()=>document.removeEventListener("mousedown",h);
  },[active]);
}
function useDebounced(value,ms){const [v,setV]=useState(value);useEffect(()=>{const t=setTimeout(()=>setV(value),ms);return()=>clearTimeout(t);},[value,ms]);return v;}

// ─── Icons (single stroke set) ────────────────────────────────────────────────
const ICONS={
  summary:"M3 3h7v9H3zM14 3h7v5h-7zM14 12h7v9h-7zM3 16h7v5H3z",
  history:"M3 12a9 9 0 1 0 3-6.7M3 4v5h5M12 7v5l3 2",
  scripts:"M4 17l6-6-6-6M12 19h8",
  dashboards:"M4 20V10M10 20V4M16 20v-7M22 20H2",
  sharepoint:"M12 3v12M7 10l5 5 5-5M4 21h16",
  schedules:"M8 2v4M16 2v4M3 9h18M5 4h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z",
  users:"M16 20v-2a4 4 0 0 0-8 0v2M12 11a3 3 0 1 0 0-6a3 3 0 1 0 0 6M22 20v-2a3 3 0 0 0-2-2.8M17 4.2a3 3 0 0 1 0 5.6",
  feedback:"M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z",
  search:"M11 4a7 7 0 1 0 0 14a7 7 0 1 0 0-14M21 21l-4.4-4.4",
  plus:"M12 5v14M5 12h14",
  x:"M18 6L6 18M6 6l12 12",
  check:"M20 6L9 17l-5-5",
  play:"M6 4l14 8-14 8z",
  stop:"M6 6h12v12H6z",
  edit:"M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z",
  trash:"M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6M10 11v6M14 11v6",
  chevL:"M15 18l-6-6 6-6",chevR:"M9 18l6-6-6-6",chevD:"M6 9l6 6 6-6",chevU:"M18 15l-6-6-6 6",
  sun:"M12 3v2M12 19v2M5 5l1.5 1.5M17.5 17.5L19 19M3 12h2M19 12h2M5 19l1.5-1.5M17.5 6.5L19 5M12 8a4 4 0 1 0 0 8a4 4 0 1 0 0-8",
  moon:"M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z",
  logout:"M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9",
  grid:"M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z",
  list:"M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01",
  timeline:"M3 6h8M7 12h10M5 18h12M21 3v18",
  clock:"M12 3a9 9 0 1 0 0 18a9 9 0 1 0 0-18M12 7v5l3 2",
  mail:"M4 4h16a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2zM22 6l-10 7L2 6",
  upload:"M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12",
  info:"M12 3a9 9 0 1 0 0 18a9 9 0 1 0 0-18M12 16v-4M12 8h.01",
  warn:"M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0zM12 9v4M12 17h.01",
  ext:"M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6M15 3h6v6M10 14L21 3",
  refresh:"M23 4v6h-6M1 20v-6h6M3.5 9a9 9 0 0 1 14.9-3.4L23 10M1 14l4.6 4.4A9 9 0 0 0 20.5 15",
  folder:"M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z",
  link:"M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7",
  star:"M12 2l3.1 6.3 6.9 1-5 4.9 1.2 6.8L12 17.8 5.8 21l1.2-6.8-5-4.9 6.9-1z",
  pause:"M7 5h3v14H7zM14 5h3v14h-3z",
  file:"M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6",
  user:"M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2M12 3a4 4 0 1 0 0 8a4 4 0 1 0 0-8",
  bolt:"M13 2L3 14h9l-1 8 10-12h-9z",
  terminal:"M4 17l6-6-6-6M12 19h8",
  lock:"M5 11h14v10H5zM8 11V7a4 4 0 0 1 8 0v4",
  filter:"M22 3H2l8 9.5V19l4 2v-8.5z",
  up:"M12 19V5M5 12l7-7 7 7",
  share:"M18 8a3 3 0 1 0 0-6a3 3 0 1 0 0 6M6 15a3 3 0 1 0 0-6a3 3 0 1 0 0 6M18 22a3 3 0 1 0 0-6a3 3 0 1 0 0 6M8.6 13.5l6.8 4M15.4 6.5l-6.8 4",
  msg:"M21 11.5a8.4 8.4 0 0 1-9 8.4 8.6 8.6 0 0 1-3.8-.9L3 21l1.9-5.2A8.4 8.4 0 0 1 12 3a8.4 8.4 0 0 1 9 8.5z",
  eye:"M1 12s4-8 11-8 11 8 11 8-4 8-11 8S1 12 1 12zM12 9a3 3 0 1 0 0 6a3 3 0 1 0 0-6",
};
function Icon({name,size=16,sw=2,style,className}){
  const d=ICONS[name]||name;
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={sw} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" style={{flexShrink:0,...style}} className={className}>
    {d.split(/(?=M)/).map((p,i)=><path key={i} d={p}/>)}
  </svg>;
}
function LogoMark({size=34}){
  return <div className="logo-mark" style={{width:size,height:size,borderRadius:size*.3}}>
    <svg width={size*.56} height={size*.56} viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2.4" strokeLinecap="round" aria-hidden="true"><path d="M12 12c-2-2.5-4-4-6-4a4 4 0 0 0 0 8c2 0 4-1.5 6-4z"/><path d="M12 12c2 2.5 4 4 6 4a4 4 0 0 0 0-8c-2 0-4 1.5-6 4z"/></svg>
  </div>;
}

// ─── Status & type ────────────────────────────────────────────────────────────
const STATUS_CFG={
  success:["ok","Success"],partial:["warn","Partial"],failed:["bad","Failed"],
  running:["run","Running"],started:["run","Running"],stopped:["warn","Stopped"],
  active:["ok","Active"],inactive:["idle","Paused"],paused:["idle","Paused"],scheduled:["idle","Scheduled"],
  open:["bad","Open"],"in review":["run","In review"],resolved:["ok","Resolved"],
};
function StatusChip({status,label}){
  const c=STATUS_CFG[(status||"").toLowerCase()]||["idle",status||"—"];
  const run=c[0]==="run";
  return <span className={"chip chip-"+c[0]}><span className={"dot"+(run?" blink":"")}/>{label||c[1]}</span>;
}
const TYPE_LABEL={script:"Script",tableau:"Tableau",sharepoint:"SharePoint",app:"App"};
function TypeTag({type}){
  const t=type||"script";const cls=t==="app"?"script":t;
  return <span className="tag"><span className={"tdot "+cls}/>{TYPE_LABEL[t]||t}</span>;
}
function Avatar({name,size=32}){
  return <span className="avatar" style={{width:size,height:size,fontSize:Math.max(10,size*.36)}}>{nameToInitials(name)}</span>;
}
function Spinner({size=16,color}){return <span className="spinner" style={{width:size,height:size,color:color||undefined}}/>;}
function Skel({w="70%",h=13,style}){return <div className="skel" style={{width:w,height:h,...style}}/>;}
function SkelRows({rows=6,cols=5}){
  return <tbody>{Array.from({length:rows}).map((_,i)=><tr key={i}>{Array.from({length:cols}).map((_,j)=><td key={j}><Skel w={`${50+((i*7+j*13)%40)}%`}/></td>)}</tr>)}</tbody>;
}
function Empty({title,sub,action,icon="file"}){
  return <div className="empty fade">
    <div style={{width:46,height:46,borderRadius:14,background:"var(--surface2)",margin:"0 auto 14px",display:"flex",alignItems:"center",justifyContent:"center"}}><Icon name={icon} size={20}/></div>
    <div className="t">{title}</div>
    {sub&&<div className="small" style={{marginBottom:action?14:0}}>{sub}</div>}
    {action}
  </div>;
}
function Switch({on,onChange,disabled,label}){
  return <button type="button" role="switch" aria-checked={!!on} aria-label={label} disabled={disabled} className={"switch"+(on?" on":"")} onClick={e=>{e.stopPropagation();onChange&&onChange(!on);}}><span className="knob"/></button>;
}
function Seg({value,onChange,options,wide,ariaLabel}){
  return <div className={"seg"+(wide?" wide":"")} role="group" aria-label={ariaLabel}>
    {options.map(o=>{const [v,l,extra]=Array.isArray(o)?o:[o.v,o.l,o.extra];return <button key={v} type="button" className={value===v?"on":""} aria-pressed={value===v} onClick={()=>onChange(v)}>{l}{extra}</button>;})}
  </div>;
}
function SearchBox({value,onChange,placeholder,style}){
  return <div className="search" style={style}><Icon name="search" size={15}/><input className="field" value={value} onChange={e=>onChange(e.target.value)} placeholder={placeholder} aria-label={placeholder}/></div>;
}
function ErrNote({children}){return children?<div className="note note-bad" style={{marginBottom:14}}><Icon name="warn" size={16}/><div>{children}</div></div>:null;}

function usePagination(items,perPage){
  const [page,setPage]=useState(1);
  const pp=perPage||20;const total=Math.max(1,Math.ceil((items.length||0)/pp));
  const safe=page>total?total:page;
  return {page:safe,total,slice:items.slice((safe-1)*pp,safe*pp),setPage,reset:()=>setPage(1)};
}
function Pagination({page,total,onPage}){
  if(!total||total<=1)return null;
  const pages=[];for(let i=1;i<=total;i++)if(i===1||i===total||Math.abs(i-page)<=1)pages.push(i);
  const out=[];pages.forEach((p,j)=>{if(j>0&&p-pages[j-1]>1)out.push(-p);out.push(p);});
  return <div style={{display:"flex",alignItems:"center",justifyContent:"center",gap:6,padding:"14px 0 2px"}}>
    <button className="btn btn-sm" disabled={page<=1} onClick={()=>onPage(page-1)} aria-label="Previous page"><Icon name="chevL" size={14}/></button>
    {out.map(p=>p<0?<span key={p} className="muted">…</span>:<button key={p} className={"btn btn-sm"+(p===page?" btn-primary":"")} onClick={()=>onPage(p)} style={{minWidth:32}}>{p}</button>)}
    <button className="btn btn-sm" disabled={page>=total} onClick={()=>onPage(page+1)} aria-label="Next page"><Icon name="chevR" size={14}/></button>
  </div>;
}

// ─── Modal / drawer / confirm ─────────────────────────────────────────────────
// Pop-ups are drawn straight into <body>, so they always line up with the
// browser window (not the animated page area) and cover the sidebar too.
function Portal({children}){return ReactDOM.createPortal(children,document.body);}
function Modal({title,sub,onClose,children,footer,width=560,closeOnOverlay=false}){
  useEffect(()=>{const h=e=>{if(e.key==="Escape")onClose&&onClose();};document.addEventListener("keydown",h);return()=>document.removeEventListener("keydown",h);},[onClose]);
  return <Portal><div className="overlay" onMouseDown={e=>{if(closeOnOverlay&&e.target===e.currentTarget)onClose&&onClose();}}>
    <div className="modal" role="dialog" aria-modal="true" aria-label={typeof title==="string"?title:undefined} style={{width}}>
      <div className="modal-head">
        <div style={{minWidth:0}}><div className="modal-title">{title}</div>{sub&&<div className="card-sub" style={{marginTop:2}}>{sub}</div>}</div>
        <button className="btn btn-quiet btn-sm btn-icon" onClick={onClose} aria-label="Close"><Icon name="x" size={16}/></button>
      </div>
      <div className="modal-body">{children}</div>
      {footer&&<div className="modal-foot">{footer}</div>}
    </div>
  </div></Portal>;
}
function Drawer({title,sub,onClose,children,footer,width=640}){
  useEffect(()=>{const h=e=>{if(e.key==="Escape")onClose();};document.addEventListener("keydown",h);return()=>document.removeEventListener("keydown",h);},[onClose]);
  return <Portal>
    <div className="drawer-ov" onClick={onClose}/>
    <aside className="drawer" role="dialog" aria-modal="true" style={{width}}>
      <div className="modal-head">
        <div style={{minWidth:0}}><div className="modal-title trunc">{title}</div>{sub&&<div className="card-sub" style={{marginTop:2}}>{sub}</div>}</div>
        <button className="btn btn-quiet btn-sm btn-icon" onClick={onClose} aria-label="Close"><Icon name="x" size={16}/></button>
      </div>
      <div className="modal-body">{children}</div>
      {footer&&<div className="modal-foot">{footer}</div>}
    </aside>
  </Portal>;
}
function ConfirmDialog({cfg,onDone}){
  const [busy,setBusy]=useState(false);
  return <Modal title={cfg.title||"Are you sure?"} onClose={()=>onDone(false)} width={440}
    footer={<>
      <button className="btn" onClick={()=>onDone(false)} disabled={busy}>Cancel</button>
      <button className={"btn "+(cfg.danger?"btn-danger-solid":"btn-primary")} disabled={busy} autoFocus onClick={()=>{setBusy(true);onDone(true);}}>{cfg.confirmLabel||"Confirm"}</button>
    </>}>
    <div style={{fontSize:14,color:"var(--text2)",lineHeight:1.6}}>{cfg.body}</div>
  </Modal>;
}
function Toasts({items}){
  return <div className="toasts" aria-live="polite">{items.map(t=><div key={t.id} className={"toast"+(t.kind==="bad"?" bad":"")}>{t.kind==="bad"?<Icon name="warn" size={15}/>:<Icon name="check" size={15}/>}{t.msg}</div>)}</div>;
}

// ─── Small shared form pieces (kept from the original app) ───────────────────
const PRESET_CATEGORIES=["Reports","Data Sync","Maintenance","ETL","Notifications","Exports","Security","Finance","HR","IT Operations","Data Quality","Monitoring","Archive","Custom…"];
function CategoryInput({value,onChange}){
  const [custom,setCustom]=useState(!PRESET_CATEGORIES.includes(value)&&value&&value!=="General");
  if(custom){
    return <div style={{display:"flex",gap:6}}>
      <input className="field" value={value} onChange={e=>onChange(e.target.value)} placeholder="Enter custom category…" autoFocus/>
      <button type="button" className="btn" onClick={()=>{onChange("General");setCustom(false);}}>Cancel</button>
    </div>;
  }
  return <select className="field" value={value} onChange={e=>{if(e.target.value==="Custom…")setCustom(true);else onChange(e.target.value);}}>
    <option value="">Select category…</option>
    {value==="General"&&<option value="General">General</option>}
    {PRESET_CATEGORIES.map(c=><option key={c} value={c}>{c}</option>)}
    {value&&value!=="General"&&!PRESET_CATEGORIES.includes(value)&&<option value={value}>{value}</option>}
  </select>;
}

function EmailPicker({value=[],onChange,placeholder}){
  const [q,setQ]=useState("");const [res,setRes]=useState([]);const [open,setOpen]=useState(false);const [loading,setLoading]=useState(false);
  const timer=useRef(null);const wrap=useRef(null);const [names,setNames]=useState({});
  useOutside(wrap,()=>setOpen(false));
  useEffect(()=>{
    const unknown=value.filter(e=>!names[e]);if(!unknown.length)return;
    unknown.forEach(async email=>{try{const d=await api.searchUsers(email);const u={};d.forEach(x=>{if(x.email&&x.fullname)u[x.email]=x.fullname;});setNames(r=>({...r,...u}));}catch(e){}});
  },[value.join(",")]);
  const search=v=>{setQ(v);clearTimeout(timer.current);if(v.length<2){setRes([]);setOpen(false);return;}
    timer.current=setTimeout(async()=>{setLoading(true);try{const d=await api.searchUsers(v);const u={};d.forEach(x=>{if(x.email&&x.fullname)u[x.email]=x.fullname;});setNames(r=>({...r,...u}));setRes(d);setOpen(d.length>0||v.includes("@"));}catch(e){setRes([]);}finally{setLoading(false);}},280);};
  const add=email=>{if(email&&!value.includes(email))onChange([...value,email]);setQ("");setRes([]);setOpen(false);};
  const remove=email=>onChange(value.filter(e=>e!==email));
  const addManual=()=>{const e=q.trim();if(e.includes("@"))add(e);};
  const nm=email=>names[email]||email;
  return <div ref={wrap}>
    {value.length>0&&<div style={{display:"flex",flexWrap:"wrap",gap:6,marginBottom:8}}>
      {value.map(email=><span key={email} className="chip chip-run" style={{padding:"3px 6px 3px 4px",fontWeight:500}}>
        <Avatar name={nm(email)} size={20}/>{nm(email)}
        <button type="button" onClick={()=>remove(email)} aria-label={"Remove "+email} style={{border:"none",background:"none",cursor:"pointer",color:"inherit",padding:0,display:"flex"}}><Icon name="x" size={13}/></button>
      </span>)}
    </div>}
    <div style={{position:"relative"}}>
      <input className="field" value={q} onChange={e=>search(e.target.value)} onKeyDown={e=>{if(e.key==="Enter"){e.preventDefault();addManual();}}} onBlur={addManual} placeholder={placeholder||"Search by name, email, or department…"}/>
      {loading&&<div style={{position:"absolute",right:12,top:11}}><Spinner size={14}/></div>}
      {open&&<div className="popover" style={{top:"calc(100% + 4px)",left:0,right:0,maxHeight:260,overflowY:"auto",padding:4}}>
        {res.map(u=>{const already=value.includes(u.email);return <div key={u.email} className="menu-item" onMouseDown={e=>e.preventDefault()} onClick={()=>!already&&add(u.email)} style={{opacity:already?.55:1}}>
          <Avatar name={u.fullname||u.email} size={28}/>
          <div style={{flex:1,minWidth:0}}><div style={{fontWeight:600}} className="trunc">{u.fullname||u.email}</div><div className="small muted trunc">{[u.department,u.title].filter(Boolean).join(" · ")}</div></div>
          <span className="small muted trunc" style={{maxWidth:180}}>{u.email}</span>
          {already&&<Icon name="check" size={14}/>}
        </div>;})}
        {q.includes("@")&&!res.find(r=>r.email===q.trim())&&<div className="menu-item" onMouseDown={e=>e.preventDefault()} onClick={addManual} style={{color:"var(--accentText)",fontWeight:600}}><Icon name="plus" size={14}/>Add "{q.trim()}"</div>}
      </div>}
    </div>
  </div>;
}

function TimePicker({value,onChange}){
  const [open,setOpen]=useState(false);const ref=useRef(null);
  const [hh24,mm]=(value||"00:00").split(":").map(s=>parseInt(s,10)||0);
  const period=hh24>=12?"PM":"AM";const hh12=(hh24%12)===0?12:hh24%12;
  useOutside(ref,()=>setOpen(false),open);
  const setParts=(h12,m,p)=>{let h=h12%12;if(p==="PM")h+=12;onChange(`${String(h).padStart(2,"0")}:${String(m).padStart(2,"0")}`);};
  const item=on=>({padding:"5px 0",textAlign:"center",fontSize:13,cursor:"pointer",borderRadius:6,background:on?"var(--accentSoft)":"transparent",color:on?"var(--accentText)":"var(--text)",fontWeight:on?700:400});
  return <div ref={ref} style={{position:"relative"}}>
    <button type="button" className="field" onClick={()=>setOpen(o=>!o)} style={{textAlign:"left",display:"flex",alignItems:"center",justifyContent:"space-between",cursor:"pointer"}}>
      <span>{`${String(hh12).padStart(2,"0")}:${String(mm).padStart(2,"0")} ${period}`}</span><Icon name="clock" size={15} style={{color:"var(--text3)"}}/>
    </button>
    {open&&<div className="popover" style={{top:"calc(100% + 4px)",left:0,display:"flex",gap:4,padding:8,width:190}}>
      <div style={{maxHeight:170,overflowY:"auto",flex:1}}>{Array.from({length:12},(_,i)=>i+1).map(h=><div key={h} style={item(h===hh12)} onClick={()=>setParts(h,mm,period)}>{String(h).padStart(2,"0")}</div>)}</div>
      <div style={{maxHeight:170,overflowY:"auto",flex:1}}>{Array.from({length:60},(_,i)=>i).map(m=><div key={m} style={item(m===mm)} onClick={()=>setParts(hh12,m,period)}>{String(m).padStart(2,"0")}</div>)}</div>
      <div style={{display:"flex",flexDirection:"column",gap:4,flex:1}}>{["AM","PM"].map(p=><div key={p} style={item(p===period)} onClick={()=>setParts(hh12,mm,p)}>{p}</div>)}</div>
    </div>}
  </div>;
}