// ─── schedules.jsx ───────────────────────────────────────────────────────────
// Schedules: the place things actually run. Around-now strip + list, run now / stop,
// active switch, and the three schedule forms.

function schedName(s){return s.schedule_type==="sharepoint"?s.name:s.schedule_type==="tableau"?(s.name||s.dashboard_name||`Tableau #${s.id}`):(s.script_name||s.name||`Script #${s.script_id}`);}
function schedWhen(s){
  const isScript=(s.schedule_type||"script")==="script";
  const rec=isScript?(s.frequency||"daily"):(s.recurrence||"daily");
  const tz=s.timezone||TZ;
  const t=isScript?fmtTime(s.run_time):(s.run_at_utc?new Date(s.run_at_utc+"Z").toLocaleTimeString("en-US",{hour:"numeric",minute:"2-digit",hour12:true,timeZone:tz}):"—");
  const days=Array.isArray(s.days_of_week)?s.days_of_week:typeof s.days_of_week==="string"?s.days_of_week.split(",").map(x=>x.trim()).filter(Boolean):[];
  if(rec==="once")return s.run_at_utc?`Once · ${fmtDate(s.run_at_utc)}`:"Once";
  if(rec==="hourly")return `Every ${s.interval_hours||1}h${s.hourly_end_time?` until ${fmtTime(s.hourly_end_time)}`:""}${days.length?` · ${days.map(d=>d.slice(0,3)).join(", ")}`:" · weekdays"}`;
  if(rec==="weekly")return `Weekly · ${days.map(d=>d.slice(0,3)).join(", ")||"—"} · ${t}`;
  if(rec==="monthly"||rec==="quarterly")return `${cap(rec)} · ${getWeekLabel(rec,s.week_of_month)} · ${t}`;
  return `Daily · ${t}`;
}
// Occurrences in the next 24h (next_run_utc, plus repeats for hourly schedules)
function occurrences(s,now,end){
  if(!s.is_active||!s.next_run_utc)return [];
  const first=toDate(s.next_run_utc).getTime();const out=[];
  const rec=(s.schedule_type||"script")==="script"?s.frequency:s.recurrence;
  if(rec==="hourly"){
    const step=(s.interval_hours||1)*3600e3;
    for(let t=first;t<=end&&out.length<48;t+=step){
      const hm=new Date(t).toLocaleTimeString("en-GB",{hour:"2-digit",minute:"2-digit",hour12:false,timeZone:s.timezone||TZ});
      if(!s.hourly_end_time||hm<=s.hourly_end_time)out.push(t);
    }
  }else{if(first>=now-60e3&&first<=end)out.push(first);if(rec==="daily"&&first+86400e3<=end)out.push(first+86400e3);}
  return out;
}

// "Last 12 hours · next 12 hours" strip at the top of Schedules.
// Left of now: runs that happened (green passed, red failed, amber stopped, blue running).
// Right of now: runs coming up (hollow grey ring; the tooltip shows each one's type).
// Runs within ~20px of each other merge into one bubble with a count; its ring is
// split by result (past); coming-up bubbles have a plain grey ring. Hover lists them; click:
//   past dot → that run's log · past bubble → pinned list of its runs (click one for its log)
//   future dot → highlight the schedule in the list · future bubble → list shows just those schedules
const RESULT_COLOR={success:"var(--ok)",failed:"var(--bad)",stopped:"var(--warn)",running:"var(--accent)",started:"var(--accent)"};
// Coming-up runs use one neutral colour, so they never look like a type (Script is purple) or a result
const UPCOMING="var(--text2)";
const RESULT_WORD={success:"passed",failed:"failed",stopped:"stopped",running:"running",started:"running"};
function ringArcs(cx,cy,r,parts){
  const tot=parts.reduce((a,p)=>a+p.n,0);if(!tot)return null;
  const live=parts.filter(p=>p.n>0);
  if(live.length===1)return <circle cx={cx} cy={cy} r={r} fill="none" stroke={live[0].color} strokeWidth="3.5"/>;
  let a=-Math.PI/2;const gap=.16;
  return live.map((p,i)=>{const b=a+2*Math.PI*p.n/tot;const s=a,e=b-gap;a=b;
    const x1=cx+r*Math.cos(s),y1=cy+r*Math.sin(s),x2=cx+r*Math.cos(e),y2=cy+r*Math.sin(e);
    return <path key={i} d={`M${x1},${y1} A${r},${r} 0 ${e-s>Math.PI?1:0} 1 ${x2},${y2}`} fill="none" stroke={p.color} strokeWidth="3.5" strokeLinecap="round"/>;});
}
function AroundNow({schedules,runs,onPickSchedule,onPickMany,onOpenRun}){
  const wrap=useRef(null);const W=useWidth(wrap,900);
  const [hover,setHover]=useState(null);const [pinned,setPinned]=useState(null);
  const now=useNow(60000);const from=now-12*3600e3,to=now+12*3600e3;
  const pad=18,iw=Math.max(100,W-pad*2);const x=t=>pad+(t-from)/(to-from)*iw;const nowX=x(now);
  const cy=40;
  const past=runs.filter(l=>{const t=toDate(l.started_at)?.getTime();return t&&t>=from&&t<=now;})
    .map(l=>({t:toDate(l.started_at).getTime(),log:l})).sort((a,b)=>a.t-b.t);
  const future=[];schedules.forEach(s=>occurrences(s,now,to).forEach(t=>future.push({t,s})));future.sort((a,b)=>a.t-b.t);
  const group=(pts,side)=>{const out=[];pts.forEach(p=>{const px=x(p.t);const c=out[out.length-1];if(c&&px-c.x<20)c.items.push(p);else out.push({x:px,t:p.t,items:[p],side});});return out;};
  const clusters=[...group(past,"past"),...group(future,"next")];
  useEffect(()=>{if(!pinned)return;const h=e=>{if(!e.target.closest(".an-pop,.an-dot"))setPinned(null);};document.addEventListener("mousedown",h);return()=>document.removeEventListener("mousedown",h);},[pinned]);
  const ticks=[];const h0=new Date(from);h0.setMinutes(0,0,0);for(let t=h0.getTime()+3600e3;t<to;t+=3600e3){if(new Date(t).getHours()%3===0)ticks.push(t);}
  const statusOf=l=>l.status==="started"?"running":l.status;
  const click=(c,i)=>{
    if(c.side==="past"){if(c.items.length===1)onOpenRun(c.items[0].log);else setPinned(pinned===i?null:i);}
    else{if(c.items.length===1)onPickSchedule(c.items[0].s);else onPickMany(c.items.map(p=>p.s),c.t);}
  };
  const show=pinned!=null?pinned:hover;const c=show!=null?clusters[show]:null;
  return <div ref={wrap} style={{position:"relative",height:96}}>
    <svg width={W} height={96} className="chart-svg" role="img" aria-label={`${past.length} runs in the last 12 hours, ${future.length} in the next 12`}>
      <rect x={pad} y={cy-17} width={Math.max(0,nowX-pad)} height={34} rx={9} fill="var(--surface2)"/>
      <line x1={pad} x2={W-pad} y1={cy} y2={cy} stroke="var(--border2)" strokeWidth="2" strokeLinecap="round"/>
      {ticks.map(t=><text key={t} x={x(t)} y={cy+34} textAnchor="middle">{fmtClock(t).replace(":00","")}</text>)}
      <line x1={nowX} x2={nowX} y1={cy-24} y2={cy+20} stroke="var(--accent)" strokeWidth="2"/>
      <text x={nowX} y={cy+52} textAnchor="middle" style={{fill:"var(--accentText)",fontWeight:700}}>NOW</text>
      <text x={pad+4} y={cy+52}>← last 12 hours</text><text x={W-pad-4} y={cy+52} textAnchor="end">next 12 hours →</text>
      {clusters.map((c,i)=>{const multi=c.items.length>1;
        let mark;
        if(!multi&&c.side==="past"){const st=statusOf(c.items[0].log);mark=<circle cx={c.x} cy={cy} r={6.5} fill={RESULT_COLOR[st]||"var(--text3)"} stroke="var(--surface)" strokeWidth="2" className={st==="running"?"blink":undefined}/>;}
        else if(!multi){mark=<circle cx={c.x} cy={cy} r={6} fill="var(--surface)" stroke={UPCOMING} strokeWidth="3"/>;}
        else{const parts=c.side==="past"
            ?["success","failed","stopped","running"].map(k=>({n:c.items.filter(p=>statusOf(p.log)===k).length,color:RESULT_COLOR[k]}))
            :[{n:c.items.length,color:UPCOMING}];
          mark=<g><circle cx={c.x} cy={cy} r={13} fill="var(--surface)"/>{ringArcs(c.x,cy,13,parts)}
            <text x={c.x} y={cy+4} textAnchor="middle" style={{fill:"var(--text)",fontWeight:800,fontSize:11.5}}>{c.items.length>99?"99+":c.items.length}</text></g>;}
        return <g key={c.side+i} className="hit pop an-dot" style={{animationDelay:`${i*20}ms`,transformOrigin:`${c.x}px ${cy}px`}}
          onMouseEnter={()=>setHover(i)} onMouseLeave={()=>setHover(null)} onClick={()=>click(c,i)}
          role="button" tabIndex={0} aria-label={`${c.items.length} run${c.items.length>1?"s":""} at ${fmtClock(c.t)}`} onKeyDown={e=>{if(e.key==="Enter")click(c,i);}}>
          {mark}<circle cx={c.x} cy={cy} r={16} fill="transparent"/></g>;})}
    </svg>
    {past.length===0&&future.length===0&&<div className="small muted" style={{position:"absolute",top:4,left:pad}}>Nothing ran in the last 12 hours and nothing is due in the next 12.</div>}
    {c&&<div className={"tip fade"+(pinned!=null?" an-pop":"")} style={{left:Math.min(Math.max(c.x-140,0),Math.max(0,W-290)),top:cy+20,zIndex:30,whiteSpace:"normal",width:280,maxHeight:280,overflowY:"auto",pointerEvents:pinned!=null?"auto":"none"}}>
      <div style={{fontWeight:700,marginBottom:4}}>{fmtWhen(c.t)} · {c.items.length} run{c.items.length>1?"s":""}
        {c.side==="past"&&c.items.some(p=>p.log.status==="failed")?` · ${c.items.filter(p=>p.log.status==="failed").length} failed`:""}</div>
      {c.items.slice(0,12).map((p,j)=>c.side==="past"
        ?<div key={j} className={pinned!=null?"an-row":undefined} onClick={pinned!=null?()=>{setPinned(null);onOpenRun(p.log);}:undefined} style={{display:"flex",alignItems:"center",gap:7,padding:"2px 4px",borderRadius:6}}>
          <span className="dot8" style={{background:RESULT_COLOR[statusOf(p.log)]||"var(--text3)",boxShadow:"0 0 0 1.5px var(--tipText)"}}/>
          <span className="trunc" style={{flex:1}}>{p.log.script_name||p.log.schedule_name||"Run"}</span>
          <span style={{opacity:.75,whiteSpace:"nowrap"}}>{RESULT_WORD[p.log.status]||p.log.status}{p.log.duration_ms?` · ${msStr(p.log.duration_ms)}`:""}</span></div>
        :<div key={j} style={{display:"flex",alignItems:"center",gap:7,padding:"2px 4px"}}>
          <span className="dot8" style={{background:TYPE_COLOR[p.s.schedule_type||"script"],boxShadow:"0 0 0 1.5px var(--tipText)"}}/>
          <span className="trunc" style={{flex:1}}>{schedName(p.s)}</span><span style={{opacity:.75,whiteSpace:"nowrap"}}>{fmtClock(p.t)}</span></div>)}
      {c.items.length>12&&<div style={{opacity:.7,marginTop:2}}>+{c.items.length-12} more</div>}
      <div style={{opacity:.7,marginTop:4}}>{c.side==="past"?(c.items.length>1?(pinned!=null?"Click a run to open its log":"Click to pick a run"):"Click to open its log"):(c.items.length>1?"Click to show just these in the list":"Click to find it in the list")}</div>
    </div>}
  </div>;
}

// ─── Sharing ──────────────────────────────────────────────────────────────────
// my_access on each schedule: "owner" | "admin" | "edit" | "view"
const canEdit=s=>(s?.my_access||"owner")!=="view";
const isShared=s=>s?.my_access==="edit"||s?.my_access==="view";
function ShareTag({s}){
  if(isShared(s))return <span className="tag shared-by" title={s.my_access==="view"?"Shared with you · view only":"Shared with you · can edit"}><Icon name={s.my_access==="view"?"eye":"share"} size={12}/>Shared by {s.owner_name||"someone"}{s.my_access==="view"?" · View only":""}</span>;
  if(s.share_count>0){
    // "Shared with Priya +2"; hovering lists everyone and their access
    const ppl=s.share_people||[];const first=(ppl[0]?.name||"").split(" ")[0];
    const label=first?`Shared with ${first}${s.share_count>1?` +${s.share_count-1}`:""}`:`Shared with ${s.share_count}`;
    return <span className="tag shared-with share-hover" tabIndex={0}><Icon name="share" size={12}/>{label}
      {ppl.length>0&&<span className="tip share-tip" role="tooltip">
        <div style={{fontWeight:700,marginBottom:2}}>{s.share_count===1?"1 person has":`${s.share_count} people have`} access</div>
        {ppl.map((p,i)=><div key={i} style={{display:"flex",justifyContent:"space-between",gap:16}}><span className="trunc">{p.name}</span><span style={{opacity:.7,whiteSpace:"nowrap"}}>{p.access==="view"?"Can view":"Can edit"}</span></div>)}
        <div style={{opacity:.7,marginTop:4}}>Click Share to change</div>
      </span>}
    </span>;}
  return null;
}
// Banner at the top of an edit form opened by someone the schedule is shared with
function SharedNote({s}){
  return <>
    {isShared(s)&&<div className="note note-shared" style={{marginBottom:12}}><Icon name="share" size={16}/><div><b>Shared with you by {s.owner_name||"the owner"}.</b> You can edit, run, pause and stop this schedule. Only {(s.owner_name||"the owner").split(" ")[0]} or an admin can delete it or change its {s.schedule_type==="tableau"?"dashboard":s.schedule_type==="sharepoint"?"SharePoint site":"script"}.</div></div>}
    {s?.last_edited_by_name&&<div className="small muted" style={{display:"flex",alignItems:"center",gap:6,marginBottom:14}}><Icon name="edit" size={13}/>Last edited by <b style={{color:"var(--text2)"}}>{s.last_edited_by_name}</b> · {fmtWhen(s.last_edited_at)}</div>}
  </>;
}
const ACCESS_OPTS=[["edit","Can edit"],["view","Can view"]];
function ShareModal({schedule,onClose,onChanged}){
  const {toast}=useApp();
  const [rows,setRows]=useState(null);const [people,setPeople]=useState(()=>peek("/users/",[]));
  const [q,setQ]=useState("");const [pick,setPick]=useState(null);const [access,setAccess]=useState("edit");const [open,setOpen]=useState(false);const [busy,setBusy]=useState(false);
  const boxRef=useRef(null);useOutside(boxRef,()=>setOpen(false),open);
  useEffect(()=>{api.getShares(schedule.id).then(setRows).catch(e=>{toast(e.message,"bad");setRows([]);});api.getUsers().then(setPeople).catch(()=>{});},[schedule.id]);
  const done=r=>{setRows(r);onChanged(r.length);};
  const owner=people.find(u=>u.email===schedule.owner_email)||{name:schedule.owner_name||"Owner",email:schedule.owner_email||""};
  const taken=new Set([(owner.email||"").toLowerCase(),...(rows||[]).map(r=>r.email.toLowerCase())]);
  const ql=q.trim().toLowerCase();
  const matches=people.filter(u=>!taken.has((u.email||"").toLowerCase())&&(!ql||u.name.toLowerCase().includes(ql)||u.email.toLowerCase().includes(ql)||(u.department||"").toLowerCase().includes(ql))).slice(0,8);
  const add=async()=>{if(!pick||busy)return;setBusy(true);
    try{done(await api.addShare(schedule.id,pick.id,access));toast(`Shared with ${pick.name}`);setPick(null);setQ("");}
    catch(e){toast(e.message,"bad");}finally{setBusy(false);}};
  const change=async(r,a)=>{try{done(await api.changeShare(schedule.id,r.user_id,a));}catch(e){toast(e.message,"bad");}};
  const remove=async r=>{try{done(await api.removeShare(schedule.id,r.user_id));toast(`${r.name} no longer has access`);}catch(e){toast(e.message,"bad");}};
  return <Modal title="Share schedule" sub={schedName(schedule)} onClose={onClose} width={600} footer={<button className="btn btn-primary" onClick={onClose}>Done</button>}>
    <div className="note note-info" style={{marginBottom:16}}><Icon name="info" size={16}/><div>
      <b>Can edit</b> — edit, run, pause and stop this schedule, and test-run its script.<br/>
      <b>Can view</b> — see the schedule, its run history and logs.<br/>
      Only you and admins can delete it or change its {schedule.schedule_type==="tableau"?"dashboard":schedule.schedule_type==="sharepoint"?"SharePoint site":"script"}. Access stays until you remove it.</div></div>
    <label className="lbl">Add people</label>
    <div style={{display:"flex",gap:8,marginBottom:18}}>
      <div ref={boxRef} style={{position:"relative",flex:1,minWidth:0}}>
        {pick?<div className="field" style={{display:"flex",alignItems:"center",gap:8}}><Avatar name={pick.name} size={22}/><span className="trunc" style={{flex:1}}>{pick.name}</span>
            <button type="button" className="btn btn-quiet btn-sm btn-icon" style={{height:24,width:24}} onClick={()=>setPick(null)} aria-label="Clear"><Icon name="x" size={13}/></button></div>
          :<input className="field" value={q} onChange={e=>{setQ(e.target.value);setOpen(true);}} onFocus={()=>setOpen(true)} placeholder="Search by name or email…" aria-label="Search people"/>}
        {open&&!pick&&<div className="popover" style={{top:"calc(100% + 4px)",left:0,right:0,maxHeight:260,overflowY:"auto",padding:4}}>
          {matches.length===0?<div className="small muted" style={{padding:10}}>{people.length?"No one else matches. People appear here once they've signed in to Conductor.":"Loading people…"}</div>
          :matches.map(u=><div key={u.id} className="menu-item" onClick={()=>{setPick(u);setOpen(false);}}><Avatar name={u.name} size={28}/>
            <div style={{flex:1,minWidth:0}}><div style={{fontWeight:600}} className="trunc">{u.name}</div><div className="small muted trunc">{[u.email,u.department].filter(Boolean).join(" · ")}</div></div></div>)}
        </div>}
      </div>
      <select className="field" style={{width:120}} value={access} onChange={e=>setAccess(e.target.value)} aria-label="Access for new person">{ACCESS_OPTS.map(([v,l])=><option key={v} value={v}>{l}</option>)}</select>
      <button className="btn btn-primary" onClick={add} disabled={!pick||busy}>{busy?<Spinner size={14} color="#fff"/>:"Add"}</button>
    </div>
    <label className="lbl">People with access</label>
    <div className="share-row">
      <Avatar name={owner.name} size={34}/>
      <div style={{minWidth:0}}><div style={{fontWeight:600}}>{owner.name}</div><div className="small muted trunc">{owner.email}</div></div>
      <span style={{textAlign:"center",fontSize:13,fontWeight:600}}>Owner</span><span/>
    </div>
    {/* While loading, placeholder rows (one per person it's shared with) keep the window at its final height so it doesn't jump */}
    {rows==null?(!schedule.share_count?<p className="hint" style={{marginTop:10,visibility:"hidden"}}>Not shared with anyone yet.</p>:Array.from({length:schedule.share_count},(_,i)=><div key={i} className="share-row" aria-hidden="true">
      <span className="skel" style={{display:"block",width:34,height:34,borderRadius:"50%"}}/>
      <div><span className="skel" style={{display:"block",width:"45%",height:12,marginBottom:7}}/><span className="skel" style={{display:"block",width:"65%",height:10}}/></div>
      <span className="skel" style={{display:"block",height:32,borderRadius:8}}/><span/>
    </div>))
    :rows.map(r=><div key={r.user_id} className="share-row">
      <Avatar name={r.name} size={34}/>
      <div style={{minWidth:0}}><div style={{fontWeight:600}}>{r.name}{r.created_at&&<span className="small muted" style={{fontWeight:400}}> · added {fmtDateShort(r.created_at)}</span>}</div><div className="small muted trunc">{r.email}</div></div>
      <select className="field" style={{height:32,fontSize:13}} value={r.access} onChange={e=>change(r,e.target.value)} aria-label={`Access for ${r.name}`}>{ACCESS_OPTS.map(([v,l])=><option key={v} value={v}>{l}</option>)}</select>
      <button type="button" className="link-btn" style={{textAlign:"center",color:"var(--badText)",fontWeight:500,fontSize:13}} onClick={()=>remove(r)}>Remove</button>
    </div>)}
    {rows&&rows.length===0&&<p className="hint" style={{marginTop:10}}>Not shared with anyone yet.</p>}
  </Modal>;
}
// Read-only view for people who can only view a schedule
function ViewScheduleModal({s,onClose}){
  const [runs,setRuns]=useState(null);const [log,setLog]=useState(null);
  useEffect(()=>{api.getLogs({limit:300}).then(ls=>setRuns(ls.filter(l=>l.schedule_id===s.id||((s.schedule_type||"script")==="script"&&s.script_id&&l.script_id===s.script_id)).slice(0,8))).catch(()=>setRuns([]));},[s.id]);
  const to=(s.schedule_type==="tableau"?s.email_to:s.schedule_type==="sharepoint"?s.notify_email_to:(s.recipients||[]).join("; "))||"";
  return <Modal title={schedName(s)} sub={<span style={{display:"inline-flex",gap:8,alignItems:"center"}}><TypeTag type={s.schedule_type||"script"}/>Shared with you by {s.owner_name||"the owner"} · View only</span>} onClose={onClose} width={620} footer={<button className="btn btn-primary" onClick={onClose}>Close</button>}>
    <div className="kv" style={{marginBottom:14}}>
      <div><div className="k">When</div><div className="v">{schedWhen(s)}</div></div>
      <div><div className="k">Next run</div><div className="v">{!s.is_active?"Paused":s.next_run_utc?fmtWhen(s.next_run_utc):"—"}</div></div>
      <div><div className="k">Last run</div><div className="v">{s.last_run_utc?<StatusChip status={s.last_run_status||"success"}/>:"Never"}</div></div>
      {s.sharepoint_site_name&&<div><div className="k">SharePoint site</div><div className="v">{s.sharepoint_site_name}</div></div>}
    </div>
    {to&&<div className="section-box tint" style={{fontSize:13}}><span className="muted">Emails go to </span>{to}</div>}
    {s.last_edited_by_name&&<div className="small muted" style={{marginBottom:12}}>Last edited by <b style={{color:"var(--text2)"}}>{s.last_edited_by_name}</b> · {fmtWhen(s.last_edited_at)}</div>}
    <label className="lbl">Recent runs</label>
    {runs==null?<Skel/>:runs.length===0?<div className="small muted">No runs yet.</div>
      :<div className="card" style={{boxShadow:"none"}}>{runs.map(l=><div key={l.id} className="list-row click" onClick={()=>setLog(l)}>
        <span style={{width:84,flexShrink:0}}><StatusChip status={l.status}/></span><span style={{flex:1}} className="small">{fmtDate(l.started_at)}</span><span className="small muted">{msStr(l.duration_ms)}</span><Icon name="chevR" size={14} style={{color:"var(--text3)"}}/></div>)}</div>}
    {log&&<LogDrawer log={log} onClose={()=>setLog(null)}/>}
  </Modal>;
}

function Schedules({params}){
  const {user,toast,confirm,running,refreshRunning,stopRun,runsTick}=useApp();
  const admin=isAdminUser(user);
  const [items,setItems]=useState(()=>peek("/schedules/",[]).filter(x=>!(x.name||"").startsWith("[Ad-hoc]")));const [scripts,setScripts]=useState(()=>peek("/scripts/",[]));const [dashboards,setDashboards]=useState(()=>peek("/dashboards/",[]));const [sites,setSites]=useState(()=>peek("/sharepoint/sites/",[]));
  const [loading,setLoading]=useState(true);const [tab,setTab]=useState("all");const [search,setSearch]=useState("");const [owner,setOwner]=useState("all");
  const [runs,setRuns]=useState([]);const [only,setOnly]=useState(null);   // only = {ids, t} from a strip bubble
  const [openLog,setOpenLog]=useState(null);
  const [failingOnly,setFailingOnly]=useState(false);const [scope,setScope]=useState("all");const [share,setShare]=useState(null);
  const [modal,setModal]=useState(null);const [menu,setMenu]=useState(false);const [hi,setHi]=useState(null);
  const menuRef=useRef(null);useOutside(menuRef,()=>setMenu(false),menu);
  // Runs since yesterday (Pacific) for the "last 12 hours" half of the strip
  const loadRuns=()=>{const y=new Date(Date.now()-86400e3).toLocaleDateString("en-CA",{timeZone:TZ});api.getLogs({date_from:y}).then(setRuns).catch(()=>{});};
  const load=async(silent)=>{if(!silent)setLoading(true);loadRuns();
    try{const [s,sc,db,st]=await Promise.all([api.getSchedules(),api.getScripts(),api.getDashboards(),api.getSpSites().catch(()=>[])]);
      setItems(s.filter(x=>!(x.name||"").startsWith("[Ad-hoc]")));window.dispatchEvent(new Event("cond-shares-changed"));setScripts(sc);setDashboards(db);setSites(st);}
    catch(e){toast(e.message,"bad");}finally{setLoading(false);}};
  useEffect(()=>{load();},[]);
  useInterval(()=>load(true),60000);
  useEffect(()=>{if(runsTick)loadRuns();},[runsTick]);
  useEffect(()=>{
    if(!params)return;
    if(params.action==="new")setModal({type:params.type||"script",preset:params});
    if(params.openId)setHi(params.openId);
    if(params.ownerEmail){setOwner(params.ownerEmail);}
    setFailingOnly(!!params.failing);
  },[params]);
  const runningBy={};running.forEach(r=>{if(r.schedule_id)runningBy[r.schedule_id]=r;});
  // Schedules shared with me that I haven't opened yet ("New")
  const [seenTick,setSeenTick]=useState(0);
  useEffect(()=>{const h=()=>setSeenTick(t=>t+1);window.addEventListener("cond-shares-changed",h);return()=>window.removeEventListener("cond-shares-changed",h);},[]);
  const newNow=useMemo(()=>newSharedSchedules(user,items),[items,user,seenTick]);const newIds=new Set(newNow.map(s=>s.id));
  const owners=admin?Array.from(new Map(items.filter(s=>s.owner_email).map(s=>[s.owner_email,s.owner_name])).entries()):[];
  const q=search.toLowerCase();
  const anyShared=items.some(isShared);
  const base=items.filter(s=>(!failingOnly||isFailing(s))&&(scope==="all"||(scope==="shared"?isShared(s):!isShared(s)))&&(owner==="all"||s.owner_email===owner)&&(!q||schedName(s).toLowerCase().includes(q)||(s.owner_name||"").toLowerCase().includes(q)));
  const counts={all:base.length};["script","tableau","sharepoint"].forEach(t=>counts[t]=base.filter(s=>(s.schedule_type||"script")===t).length);
  const filtered=base.filter(s=>(tab==="all"||(s.schedule_type||"script")===tab)&&(!only||only.ids.includes(s.id))).sort((a,b)=>(b.is_active-a.is_active)||((a.next_run_utc?toDate(a.next_run_utc):Infinity)-(b.next_run_utc?toDate(b.next_run_utc):Infinity)));
  const P=usePagination(filtered,25);
  useEffect(()=>{P.reset();},[tab,search,owner,failingOnly,scope,only]);
  // Admins see everyone's schedules; others see theirs plus ones shared with them
  const showOwner=admin||anyShared;
  const open=s=>{if(newIds.has(s.id))markSharesSeen(user,[s]);s.my_access==="view"?setModal({type:"view",data:s}):setModal({type:s.schedule_type||"script",data:s});};
  useEffect(()=>{if(hi){const i=filtered.findIndex(s=>s.id===hi);if(i>=0)P.setPage(Math.floor(i/25)+1);setTimeout(()=>{const el=document.getElementById("sched-"+hi);if(el)el.scrollIntoView({block:"center",behavior:"smooth"});},150);}},[hi,items.length]);
  const toggle=async s=>{try{const u=await api.toggleSchedule(s.id);setItems(p=>p.map(x=>x.id===s.id?{...x,...u}:x));toast(u.is_active?"Schedule resumed":"Schedule paused");}catch(e){toast(e.message,"bad");}};
  const del=async s=>{if(!await confirm({title:"Delete this schedule?",body:`“${schedName(s)}” will stop running. Past run history is kept.`,confirmLabel:"Delete schedule",danger:true}))return;
    try{await api.deleteSchedule(s.id);toast("Schedule deleted");load(true);}catch(e){toast(e.message,"bad");}};
  const now=useNow(1000);
  // "Starting…" shows right after Run now until the run appears in the running list (or 15s pass).
  const [starting,setStarting]=useState({});
  const runNow=async s=>{setStarting(p=>({...p,[s.id]:Date.now()}));
    try{await api.runScheduleNow(s.id);toast(`Started “${schedName(s)}”`);[1000,3000].forEach(ms=>setTimeout(()=>{refreshRunning();load(true);},ms));}
    catch(e){setStarting(p=>{const n={...p};delete n[s.id];return n;});toast("Could not run: "+e.message,"bad");}};
  useEffect(()=>{const ids=Object.keys(starting);if(!ids.length)return;
    const done=ids.filter(id=>runningBy[id]||Date.now()-starting[id]>15000);
    if(done.length)setStarting(p=>{const n={...p};done.forEach(id=>delete n[id]);return n;});},[running,now]);
  const newBtn=<div ref={menuRef} style={{position:"relative"}}>
    <button className="btn btn-primary" onClick={()=>setMenu(m=>!m)} aria-haspopup="menu" aria-expanded={menu}><Icon name="plus" size={15}/>New schedule<Icon name="chevD" size={14}/></button>
    {menu&&<div className="popover" role="menu" style={{right:0,top:44,width:260,padding:6}}>
      {[["script","Script","Run a Python script"],["tableau","Tableau","Email a dashboard snapshot"],["sharepoint","SharePoint","Upload files to a site"]].map(([t,l,d])=><div key={t} role="menuitem" tabIndex={0} className="menu-item" onClick={()=>{setMenu(false);setModal({type:t});}} onKeyDown={e=>e.key==="Enter"&&(setMenu(false),setModal({type:t}))}>
        <span className="dot8" style={{background:TYPE_COLOR[t]}}/><div><div style={{fontWeight:600}}>{l}</div><div className="small muted">{d}</div></div></div>)}
    </div>}
  </div>;
  return <div style={{display:"flex",flexDirection:"column",gap:18}}>
    {newNow.length>0&&only?.label!=="New"&&<div className="new-share-banner pg"><Icon name="share" size={16}/>
      <span>{newNow.length===1?<>“{schedName(newNow[0])}” was shared with you by {newNow[0].owner_name||"someone"}</>:<>{newNow.length} schedules were shared with you since your last visit</>}</span>
      <span className="spacer"/>
      <button type="button" className="link-btn" onClick={()=>{setTab("all");setOnly({ids:newNow.map(s=>s.id),label:"New"});}}>Show {newNow.length===1?"it":"them"}</button>
      <button type="button" className="btn btn-quiet btn-sm btn-icon" onClick={()=>markSharesSeen(user,newNow)} aria-label="Dismiss" title="Mark as seen"><Icon name="x" size={14}/></button>
    </div>}
    <div className="card pg">
      <div className="card-head"><div><div className="card-title">Last 12 hours · next 12 hours</div><div className="card-sub">What happened and what's coming · hover a dot for names, click for details</div></div>
        <div className="legend"><span><i style={{background:"var(--ok)",borderRadius:"50%"}}/>Passed</span><span><i style={{background:"var(--bad)",borderRadius:"50%"}}/>Failed</span><span><i style={{background:"transparent",border:"2px solid var(--text2)",borderRadius:"50%",boxSizing:"border-box"}}/>Coming up</span><span><svg width="16" height="16" aria-hidden="true" style={{flex:"none"}}><circle cx="8" cy="8" r="6.5" fill="none" stroke="var(--text3)" strokeWidth="2"/><text x="8" y="8.5" textAnchor="middle" dominantBaseline="middle" style={{fontSize:9,fontWeight:800,fill:"var(--text2)"}}>n</text></svg>Several at once</span></div></div>
      <div style={{padding:"8px 8px 2px"}}><AroundNow schedules={base} runs={runs} onOpenRun={setOpenLog}
        onPickSchedule={s=>{setOnly(null);setTab("all");setHi(s.id);}}
        onPickMany={(ss,t)=>{setTab("all");setOnly({ids:ss.map(s=>s.id),t});}}/></div>
    </div>
    <div className="toolbar pg2">
      <div style={{display:"flex",gap:8,flexWrap:"wrap"}} role="group" aria-label="Schedule type">
        {[["all","All"],["script","Scripts"],["tableau","Tableau"],["sharepoint","SharePoint"]].map(([v,l])=><button key={v} className={"pill"+(tab===v?" on":"")} aria-pressed={tab===v} onClick={()=>setTab(v)}>{v!=="all"&&<span className="dot8" style={{background:tab===v?"#fff":TYPE_COLOR[v]}}/>}{l}<span className="count">{counts[v]}</span></button>)}
      </div>
      <SearchBox value={search} onChange={setSearch} placeholder="Search schedules…" style={{flex:"1 1 160px",maxWidth:260}}/>
      {only&&<span className="chip chip-run" style={{padding:"2px 4px 2px 10px",fontWeight:600}}>{only.label?`${only.label} · ${only.ids.length}`:`${only.ids.length} at ${fmtClock(only.t)}`}<button type="button" onClick={()=>setOnly(null)} aria-label="Show all schedules" title="Show all schedules" style={{border:"none",background:"none",color:"inherit",cursor:"pointer",display:"flex",padding:2}}><Icon name="x" size={13}/></button></span>}
      {failingOnly&&<span className="chip chip-bad" style={{padding:"2px 4px 2px 10px",fontWeight:600}}>Failing only<button type="button" onClick={()=>setFailingOnly(false)} aria-label="Show all schedules" title="Show all schedules" style={{border:"none",background:"none",color:"inherit",cursor:"pointer",display:"flex",padding:2}}><Icon name="x" size={13}/></button></span>}
      {!admin&&anyShared&&<select className="field" style={{width:"auto"}} value={scope} onChange={e=>setScope(e.target.value)} aria-label="Whose schedules"><option value="all">All schedules</option><option value="mine">Only mine</option><option value="shared">Shared with me</option></select>}
      {admin&&owners.length>0&&<select className="field" style={{width:"auto"}} value={owner} onChange={e=>setOwner(e.target.value)} aria-label="Team member"><option value="all">All TMs</option>{owners.map(([e,n])=><option key={e} value={e}>{n}</option>)}</select>}
      <span className="spacer"/>
      {newBtn}
    </div>
    <div className="card pg3"><div className="tbl-wrap"><table className="tbl sched-tbl">
      <thead><tr><th>Name</th><th>Type</th>{showOwner&&<th>Owner</th>}<th>When</th><th>Next run</th><th>Last run</th><th>Active</th><th className="actions"><span className="sr">Actions</span></th></tr></thead>
      {loading&&!items.length?<SkelRows rows={6} cols={showOwner?8:7}/>:<tbody>
        {filtered.length===0&&<tr><td colSpan={showOwner?8:7}><Empty title="No schedules" sub={items.length?"Try a different filter":"Create your first schedule"} icon="schedules"/></td></tr>}
        {P.slice.map(s=>{const r=runningBy[s.id];const p=r?runProgress(r,now):null;const st=!r&&!!starting[s.id];
          return <tr key={s.id} id={"sched-"+s.id} className={"row"+(hi===s.id?" sel":"")+(newIds.has(s.id)?" is-new":"")} style={{opacity:s.is_active?1:.55,transition:"opacity .2s"}} onClick={()=>open(s)}>
            <td className="name" style={{minWidth:200}}>
              <div style={{display:"flex",alignItems:"center",gap:8}}>{schedName(s)}{newIds.has(s.id)&&<span className="tag-new">New</span>}</div>
              {/* Tags sit side by side on one line, so a row with two tags isn't taller than the rest */}
              {((s.sharepoint_site_id&&(s.schedule_type||"script")!=="sharepoint")||isShared(s)||s.share_count>0)&&<div className="sched-tags">
                {s.sharepoint_site_id&&(s.schedule_type||"script")!=="sharepoint"&&<span className="tag" title="Also posts to SharePoint">+ SharePoint</span>}<ShareTag s={s}/></div>}
              {r&&<div style={{marginTop:6,maxWidth:300}}><div className={"progress"+(p.warn?" warn":"")+(p.pct==null?" indet":"")}><div style={{width:(p.pct||0)+"%"}}/></div><div className="small muted" style={{fontWeight:400,marginTop:3}}>Running · {p.text}</div></div>}
            </td>
            <td><TypeTag type={s.schedule_type||"script"}/></td>
            {showOwner&&<td style={{whiteSpace:"nowrap"}}>{s.owner_name||"—"}</td>}
            <td className="small" style={{minWidth:130}}>{schedWhen(s)}</td>
            <td style={{whiteSpace:"nowrap"}}>{s.is_active&&s.next_run_utc?fmtWhen(s.next_run_utc):<span className="muted">—</span>}</td>
            <td>{st?<span className="starting"><span className="spinner" style={{width:10,height:10,borderWidth:2}}/>Starting…</span>:s.last_run_utc?<span title={s.last_error||""} style={{display:"inline-flex",flexDirection:"column",alignItems:"flex-start",gap:2,whiteSpace:"nowrap"}}><StatusChip status={s.last_run_status||"success"}/><span className="small muted">{fmtWhen(s.last_run_utc)}</span></span>:<span className="muted">Never</span>}</td>
            <td onClick={e=>e.stopPropagation()}><span title={canEdit(s)?undefined:"Only people who can edit can pause or resume"}><Switch on={s.is_active} disabled={!canEdit(s)} onChange={()=>toggle(s)} label={s.is_active?"Pause schedule":"Resume schedule"}/></span></td>
            {/* Fixed slots (main · share · edit · delete) so buttons line up on every row */}
            <td className="actions" onClick={e=>e.stopPropagation()}>{(()=>{const mine=!isShared(s);const ed=canEdit(s);return <>
              {!ed?<span className="act-slot main"/>:r?<button className="btn btn-danger btn-sm act-main" onClick={()=>stopRun(r)}><Icon name="stop" size={12}/>Stop</button>:<button className="btn btn-primary btn-sm act-main" disabled={st} onClick={()=>runNow(s)}><Icon name="play" size={12}/>Run now</button>}
              {mine?<button className="btn btn-sm btn-icon" onClick={()=>setShare(s)} aria-label="Share" title="Share"><Icon name="share" size={14}/></button>:<span className="act-slot"/>}
              {ed?<button className="btn btn-sm btn-icon" onClick={()=>open(s)} aria-label="Edit" title="Edit"><Icon name="edit" size={14}/></button>:<button className="btn btn-sm btn-icon" onClick={()=>open(s)} aria-label="View details" title="View details"><Icon name="eye" size={14}/></button>}
              {mine?<button className="btn btn-sm btn-icon" onClick={()=>del(s)} aria-label="Delete" title="Delete" style={{color:"var(--badText)"}}><Icon name="trash" size={14}/></button>:<span className="act-slot"/>}
            </>;})()}</td>
          </tr>;})}
      </tbody>}
    </table></div></div>
    <Pagination page={P.page} total={P.total} onPage={P.setPage}/>
    {openLog&&<LogDrawer log={openLog} onClose={()=>setOpenLog(null)}/>}
    {modal?.type==="view"&&<ViewScheduleModal s={modal.data} onClose={()=>setModal(null)}/>}
    {share&&<ShareModal schedule={share} onClose={()=>setShare(null)} onChanged={n=>setItems(p=>p.map(x=>x.id===share.id?{...x,share_count:n}:x))}/>}
    {modal?.type==="script"&&<ScheduleFormModal schedule={modal.data||null} scripts={scripts} presetScriptId={modal.preset?.scriptId} onSave={()=>{setModal(null);toast("Schedule saved");load(true);}} onClose={()=>setModal(null)}/>}
    {modal?.type==="tableau"&&<TableauScheduleModal schedule={modal.data||null} dashboards={dashboards} presetDashboardId={modal.preset?.dashboardId} onSave={()=>{setModal(null);toast("Schedule saved");load(true);}} onClose={()=>setModal(null)}/>}
    {modal?.type==="sharepoint"&&<SpScheduleModal schedule={modal.data?.schedule_type==="sharepoint"?modal.data:null} sites={sites} presetSiteId={modal.preset?.siteId} onSave={()=>{setModal(null);toast("Schedule saved");load(true);}} onClose={()=>setModal(null)}/>}
  </div>;
}