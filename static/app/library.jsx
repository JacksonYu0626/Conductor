// ─── library.jsx ─────────────────────────────────────────────────────────────
// Scripts, Dashboards and SharePoint sites — the things schedules run.

// Shared toolbar bits for library pages
function useOwnerScope(items,params){
  const {user}=useApp();const admin=isAdminUser(user);
  const [scope,setScope]=useState(admin?"mine":"all");
  const [ownerId,setOwnerId]=useState(params?.owner||null);
  useEffect(()=>{if(params?.owner){setOwnerId(params.owner);setScope("all");}},[params]);
  const ownerName=ownerId?(items.find(x=>x.owner?.id===ownerId)?.owner?.name||params?.ownerName||"this user"):null;
  const pass=x=>{
    if(ownerId)return x.owner?.id===ownerId;
    if(admin&&scope==="mine")return !x.owner||x.owner.id===user.id;
    return true;
  };
  const isMine=x=>!x.owner||x.owner.id===user.id;
  const controls=<>
    {admin&&!ownerId&&<Seg value={scope} onChange={setScope} options={[["mine","Mine"],["all","Everyone"]]} ariaLabel="Whose items"/>}
    {ownerId&&<span className="chip chip-run" style={{height:32,padding:"0 6px 0 12px"}}>Owner: {ownerName}<button className="btn btn-quiet btn-sm btn-icon" style={{height:24,width:24,color:"inherit"}} onClick={()=>setOwnerId(null)} aria-label="Clear owner filter"><Icon name="x" size={13}/></button></span>}
  </>;
  return {admin,pass,isMine,controls,showOwner:admin&&(scope==="all"||ownerId)};
}
function CategorySelect({items,value,onChange}){
  const cats=Array.from(new Set(items.map(x=>x.category).filter(Boolean))).sort();
  return <select className="field lib-filter" value={value} onChange={e=>onChange(e.target.value)} aria-label="Category"><option value="All">All categories</option>{cats.map(c=><option key={c} value={c}>{c}</option>)}</select>;
}
function lastLine(x,verb="run"){
  if(!x.last_run)return <span className="muted">Never {verb==="run"?"run":"sent"} yet</span>;
  const st=STATUS_CFG[(x.last_status||"").toLowerCase()];
  const color=st?{ok:"var(--okText)",bad:"var(--badText)",run:"var(--accentText)",warn:"var(--warnText)"}[st[0]]:undefined;
  return <span>Last {verb} · <b style={{color}}>{st?st[1]:x.last_status||"—"}</b> · {fmtWhen(x.last_run)}</span>;
}

// ─── Live test-run console ────────────────────────────────────────────────────
function TestRunModal({script,start,onClose}){
  const {user,refreshRunning,running,stopRun,toast}=useApp();
  const [log,setLog]=useState(null);const [phase,setPhase]=useState(start?"starting":"loading");const [err,setErr]=useState("");
  const startedAt=useRef(Date.now());const outRef=useRef(null);
  const kick=async()=>{
    setErr("");setLog(null);setPhase("starting");startedAt.current=Date.now();
    try{await api.runScript(script.id,user.email);refreshRunning();setPhase("running");}
    catch(e){setErr(e.message);setPhase("error");}
  };
  useEffect(()=>{if(start)kick();else setPhase("running");},[]);
  const poll=async()=>{
    try{
      const l=await api.latestLog(script.id);if(!l)return;
      // ignore the previous run until the new one appears
      if(phase==="starting"&&toDate(l.started_at).getTime()<startedAt.current-5000)return;
      setLog(l);
      if(l.status!=="running"&&l.status!=="started"){setPhase("done");refreshRunning();}
      else if(phase!=="running")setPhase("running");
    }catch(e){}
  };
  useInterval(poll,(phase==="running"||phase==="starting")?1500:null,[phase]);
  useEffect(()=>{if(outRef.current)outRef.current.scrollTop=outRef.current.scrollHeight;},[log?.output]);
  const isRun=log&&(log.status==="running"||log.status==="started");
  const runRow=running.find(r=>r.id===log?.id);
  const el=log?((log.finished_at?toDate(log.finished_at):new Date())-toDate(log.started_at)):0;
  return <Modal title={<span style={{display:"inline-flex",alignItems:"center",gap:10}}>Test run{log&&<StatusChip status={log.status}/>}</span>} sub={script.name} onClose={onClose} width={720}
    footer={<>
      <span style={{marginRight:"auto"}}/>
      {isRun&&<button className="btn btn-danger" onClick={async()=>{await stopRun(runRow||{id:log.id,log_type:"script",script_id:script.id,name:script.name});poll();}}><Icon name="stop" size={14}/>Stop</button>}
      {phase==="done"&&<button className="btn" onClick={kick}><Icon name="refresh" size={14}/>Run again</button>}
      <button className="btn btn-primary" onClick={onClose}>{isRun?"Close (keep running)":"Close"}</button>
    </>}>
    <div className="console" ref={outRef} style={{minHeight:260,maxHeight:"52vh"}}>
      {phase==="starting"&&!log&&<span style={{color:"#e3b341"}}>$ Starting {script.name}…</span>}
      {phase==="loading"&&<span style={{opacity:.6}}>Loading…</span>}
      {log?.output||""}
      {isRun&&<span className="blink">▍</span>}
      {log?.error&&<><div style={{color:"#f85149",fontWeight:700,marginTop:10}}>STDERR / error:</div><div style={{color:"#ff7b72"}}>{log.error}</div></>}
      {phase==="done"&&log&&<div style={{marginTop:12,paddingTop:10,borderTop:"1px solid #21262d",fontWeight:700,color:log.status==="success"?"#3fb950":"#f85149"}}>{log.status==="success"?"✓ Completed successfully":log.status==="stopped"?"■ Stopped":"✗ Run failed"} · {msStr(log.duration_ms||el)}</div>}
    </div>
    {isRun&&<div className="small muted" style={{marginTop:8}}>Running for {msStr(el)} · max {runRow?(runRow.timeout_sec?secStr(runRow.timeout_sec):"no limit"):secStr(script.timeout_sec||(script.script_type==="app"?null:3600))} · closing this window keeps it running (see “running” in the header)</div>}
    <ErrNote>{err}</ErrNote>
  </Modal>;
}

// Admin view of someone else's script/dashboard: details, pause schedules, delete
function AdminDetailModal({item,type,onClose,onChanged}){
  const {confirm,toast}=useApp();
  const owner=item.owner;
  const pause=async()=>{if(!await confirm({title:"Pause all schedules?",body:`Every active schedule for “${item.name}” will be paused. The owner can resume them later.`,confirmLabel:"Pause schedules"}))return;
    try{const r=type==="script"?await api.pauseScriptSchedules(item.id):await api.pauseDashboardSchedules(item.id);toast(`Paused ${r?.paused??""} schedule${r?.paused===1?"":"s"}`.replace("  "," "));onChanged();onClose();}catch(e){toast(e.message,"bad");}};
  const del=async()=>{if(!await confirm({title:`Delete this ${type}?`,body:`“${item.name}” and all of its schedules and logs will be removed. This can't be undone.`,confirmLabel:"Delete",danger:true}))return;
    try{type==="script"?await api.deleteScript(item.id):await api.deleteDashboard(item.id);toast("Deleted");onChanged();onClose();}catch(e){toast(e.message,"bad");}};
  return <Modal title={item.name} sub={`${type==="script"?"Script":"Dashboard"} · ${item.category||"General"}`} onClose={onClose} width={520}
    footer={<>{(item.schedule_count??0)>0&&<button className="btn" onClick={pause}><Icon name="pause" size={14}/>Pause all schedules</button>}<button className="btn btn-danger" onClick={del}><Icon name="trash" size={14}/>Delete</button><span style={{flex:1}}/><button className="btn btn-primary" onClick={onClose}>Close</button></>}>
    <div className="section-box tint" style={{display:"flex",alignItems:"center",gap:12}}>
      <Avatar name={owner?.name} size={38}/><div><div style={{fontWeight:600}}>{owner?.name||"—"}</div><div className="small muted mono">{owner?.email}</div>{owner?.department&&<div className="small muted">{owner.department}{owner.title?` · ${owner.title}`:""}</div>}</div>
    </div>
    <div className="kv" style={{marginBottom:14}}>
      <div><div className="k">Registered</div><div className="v">{fmtDateShort(item.created_at)}</div></div>
      <div><div className="k">Last run</div><div className="v">{item.last_run?fmtWhen(item.last_run):"Never"}</div></div>
      <div><div className="k">Last status</div><div className="v">{item.last_status?<StatusChip status={item.last_status}/>:"—"}</div></div>
      <div><div className="k">Active schedules</div><div className="v">{item.schedule_count??0}</div></div>
      {type==="script"&&<div><div className="k">Max run time</div><div className="v">{item.script_type==="app"?"No limit":secStr(item.timeout_sec||3600)}</div></div>}
    </div>
    {type==="dashboard"&&item.view_url&&<div className="note note-info" style={{marginBottom:14,wordBreak:"break-all"}}><Icon name="dashboards" size={15}/><span className="mono small">{item.view_url}</span></div>}
    {item.description&&item.description!=="No description provided."&&<p className="small muted" style={{lineHeight:1.6,margin:0}}>{item.description}</p>}
  </Modal>;
}

// "https://tableau/#/views/EOM/Pending?x" → "EOM/Pending"
function viewPath(url){return (url||"").replace(/^https?:\/\/[^/]+/,"").replace(/^\/?#?\/?(views\/)?/,"").replace(/\?.*$/,"")||"—";}
function LibraryCard({title,tags,desc,meta,status,actions,onOpen}){
  return <div className="card" style={{display:"flex",flexDirection:"column",cursor:onOpen?"pointer":"default"}} onClick={onOpen}>
    <div style={{padding:"16px 18px 12px",flex:1,display:"flex",flexDirection:"column",gap:8}}>
      <div style={{fontWeight:700,fontSize:15,lineHeight:1.35,wordBreak:"break-word"}}>{title}</div>
      <div style={{display:"flex",gap:6,flexWrap:"wrap"}}>{tags}</div>
      <p className="small muted clamp2" style={{margin:0,minHeight:38,lineHeight:1.55}}>{desc||"No description provided."}</p>
      {meta&&<div className="small muted" style={{display:"flex",gap:12,flexWrap:"wrap"}}>{meta}</div>}
    </div>
    <div className="small" style={{padding:"10px 18px",borderTop:"1px solid var(--border)",color:"var(--text2)"}}>{status}</div>
    <div style={{padding:"10px 14px 14px",display:"flex",gap:6}} onClick={e=>e.stopPropagation()}>{actions}</div>
  </div>;
}

// ─── Scripts ──────────────────────────────────────────────────────────────────
function Scripts({params}){
  const {user,toast,confirm,openTestRun,go}=useApp();
  const [items,setItems]=useState(()=>peek("/scripts/",[]));const [loading,setLoading]=useState(true);
  const [search,setSearch]=useState("");const [cat,setCat]=useState("All");
  const [view,setView]=useState(()=>lsGet("cond_scripts_view","grid"));
  const [edit,setEdit]=useState(null);const [add,setAdd]=useState(false);const [detail,setDetail]=useState(null);
  const load=async()=>{setLoading(true);try{setItems(await api.getScripts());}catch(e){toast(e.message,"bad");}finally{setLoading(false);}};
  useEffect(()=>{load();},[]);
  const O=useOwnerScope(items,params);
  useEffect(()=>{
    if(params?.action==="register")setAdd(true);
    if(params?.openId&&items.length){const s=items.find(x=>x.id===params.openId);if(s)(O.isMine(s)?setEdit(s):setDetail(s));}
  },[params,items.length]);
  const q=search.toLowerCase();
  const filtered=items.filter(s=>O.pass(s)&&(cat==="All"||s.category===cat)&&(s.name.toLowerCase().includes(q)||(s.description||"").toLowerCase().includes(q)));
  const P=usePagination(filtered,view==="grid"?12:25);
  useEffect(()=>{P.reset();},[cat,search,view]);
  const del=async s=>{if(!await confirm({title:"Delete this script?",body:`“${s.name}” and all of its schedules and logs will be removed. This can't be undone.`,confirmLabel:"Delete script",danger:true}))return;
    try{await api.deleteScript(s.id);toast("Script deleted");setEdit(null);load();}catch(e){toast(e.message,"bad");}};
  const open=s=>O.isMine(s)?setEdit(s):setDetail(s);
  const test=s=>openTestRun(s,true);
  return <div style={{display:"flex",flexDirection:"column",gap:18}}>
    <div className="toolbar pg">
      <SearchBox value={search} onChange={setSearch} placeholder="Search scripts…"/>
      {O.controls}
      <CategorySelect items={items} value={cat} onChange={setCat}/>
      <span className="spacer"/>
      <Seg value={view} onChange={v=>{setView(v);lsSet("cond_scripts_view",v);}} options={[["grid",<Icon name="grid" size={15}/>],["table",<Icon name="list" size={15}/>]]} ariaLabel="View"/>
      <button className="btn btn-primary lib-add" onClick={()=>setAdd(true)}><Icon name="plus" size={15}/>Register script</button>
    </div>
    {loading&&!items.length?<div className="grid-cards">{[0,1,2,3,4,5].map(i=><div key={i} className="card card-pad"><Skel w="60%" h={15}/><Skel w="90%" style={{marginTop:12}}/><Skel w="40%" style={{marginTop:8}}/></div>)}</div>
    :filtered.length===0?<div className="card"><Empty title="No scripts found" sub={items.length?"Try a different search or filter":"Register your first script to get started"} icon="scripts" action={!items.length&&<button className="btn btn-primary" onClick={()=>setAdd(true)}><Icon name="plus" size={15}/>Register script</button>}/></div>
    :view==="grid"?<div className="grid-cards pg2">{P.slice.map(s=><LibraryCard key={s.id} title={s.name} onOpen={()=>open(s)}
        tags={<><TypeTag type={s.script_type==="app"?"app":"script"}/><span className="tag">{s.category}</span></>}
        desc={s.description}
        meta={<><span>{s.script_type==="app"?"No time limit":`Max ${secStr(s.timeout_sec||3600)}`}</span><span>{s.schedule_count||0} schedule{s.schedule_count===1?"":"s"}</span>{O.showOwner&&s.owner&&<span>{s.owner.name}</span>}</>}
        status={lastLine(s)}
        actions={<><button className="btn btn-primary btn-sm" style={{flex:1}} onClick={()=>test(s)}><Icon name="play" size={13}/>Test run</button>
          {O.isMine(s)?<button className="btn btn-sm" style={{flex:1}} onClick={()=>setEdit(s)}><Icon name="edit" size={13}/>Edit</button>:<button className="btn btn-sm" style={{flex:1}} onClick={()=>setDetail(s)}>Details</button>}
          <button className="btn btn-sm btn-icon" title="Schedule it" aria-label="Schedule it" onClick={()=>go("schedules",{action:"new",type:"script",scriptId:s.id})}><Icon name="schedules" size={14}/></button></>}/>)}</div>
    :<div className="card pg2"><div className="tbl-wrap"><table className="tbl">
      <thead><tr><th>Name</th><th>Type</th><th>Category</th>{O.showOwner&&<th>Owner</th>}<th>Max run time</th><th>Last run</th><th>Status</th><th className="actions"><span className="sr">Actions</span></th></tr></thead>
      <tbody>{P.slice.map(s=><tr key={s.id} className="row" onClick={()=>open(s)}>
        <td className="name">{s.name}{s.description&&<div className="small muted trunc" style={{fontWeight:400,maxWidth:340}}>{s.description}</div>}</td>
        <td><TypeTag type={s.script_type==="app"?"app":"script"}/></td><td>{s.category}</td>{O.showOwner&&<td>{s.owner?.name||"—"}</td>}
        <td>{s.script_type==="app"?"No limit":secStr(s.timeout_sec||3600)}</td><td>{s.last_run?fmtWhen(s.last_run):<span className="muted">Never</span>}</td>
        <td>{s.last_status?<StatusChip status={s.last_status}/>:<span className="muted">—</span>}</td>
        <td className="actions" onClick={e=>e.stopPropagation()}><button className="btn btn-primary btn-sm" onClick={()=>test(s)}>Test run</button>{O.isMine(s)?<button className="btn btn-sm" onClick={()=>setEdit(s)}>Edit</button>:<button className="btn btn-sm" onClick={()=>setDetail(s)}>Details</button>}</td>
      </tr>)}</tbody></table></div></div>}
    <Pagination page={P.page} total={P.total} onPage={P.setPage}/>
    {add&&<ScriptFormModal onSave={r=>{setAdd(false);toast(`“${r.name}” registered`);load();}} onClose={()=>setAdd(false)}/>}
    {edit&&<ScriptFormModal script={edit} onSave={()=>{setEdit(null);toast("Changes saved");load();}} onClose={()=>setEdit(null)} onDelete={del}/>}
    {detail&&<AdminDetailModal item={detail} type="script" onClose={()=>setDetail(null)} onChanged={load}/>}
  </div>;
}

// ─── Dashboards ───────────────────────────────────────────────────────────────
function Dashboards({params}){
  const {user,toast,confirm,go}=useApp();
  const [items,setItems]=useState(()=>peek("/dashboards/",[]));const [loading,setLoading]=useState(true);
  const [search,setSearch]=useState("");const [cat,setCat]=useState("All");
  const [view,setView]=useState(()=>lsGet("cond_dash_view","grid"));
  const [edit,setEdit]=useState(null);const [add,setAdd]=useState(false);const [detail,setDetail]=useState(null);const [send,setSend]=useState(null);
  const load=async()=>{setLoading(true);try{setItems(await api.getDashboards());}catch(e){toast(e.message,"bad");}finally{setLoading(false);}};
  useEffect(()=>{load();},[]);
  const O=useOwnerScope(items,params);
  useEffect(()=>{
    if(params?.action==="register")setAdd(true);
    if(params?.openId&&items.length){const d=items.find(x=>x.id===params.openId);if(d)(O.isMine(d)?setEdit(d):setDetail(d));}
  },[params,items.length]);
  const q=search.toLowerCase();
  const filtered=items.filter(d=>O.pass(d)&&(cat==="All"||d.category===cat)&&(d.name.toLowerCase().includes(q)||(d.category||"").toLowerCase().includes(q)||(d.description||"").toLowerCase().includes(q)));
  const P=usePagination(filtered,view==="grid"?12:25);
  useEffect(()=>{P.reset();},[cat,search,view]);
  const del=async d=>{if(!await confirm({title:"Delete this dashboard?",body:`“${d.name}” and its schedules will be removed. This can't be undone.`,confirmLabel:"Delete dashboard",danger:true}))return;
    try{await api.deleteDashboard(d.id);toast("Dashboard deleted");setEdit(null);load();}catch(e){toast(e.message,"bad");}};
  const open=d=>O.isMine(d)?setEdit(d):setDetail(d);
  return <div style={{display:"flex",flexDirection:"column",gap:18}}>
    <div className="toolbar pg">
      <SearchBox value={search} onChange={setSearch} placeholder="Search dashboards…"/>
      {O.controls}
      <CategorySelect items={items} value={cat} onChange={setCat}/>
      <span className="spacer"/>
      <Seg value={view} onChange={v=>{setView(v);lsSet("cond_dash_view",v);}} options={[["grid",<Icon name="grid" size={15}/>],["table",<Icon name="list" size={15}/>]]} ariaLabel="View"/>
      <button className="btn btn-primary lib-add" onClick={()=>setAdd(true)}><Icon name="plus" size={15}/>Register dashboard</button>
    </div>
    {loading&&!items.length?<div className="grid-cards">{[0,1,2].map(i=><div key={i} className="card card-pad"><Skel w="60%" h={15}/><Skel w="90%" style={{marginTop:12}}/></div>)}</div>
    :filtered.length===0?<div className="card"><Empty title="No dashboards found" sub={items.length?"Try a different search or filter":"Register a Tableau view to start automated email delivery"} icon="dashboards" action={!items.length&&<button className="btn btn-primary" onClick={()=>setAdd(true)}><Icon name="plus" size={15}/>Register dashboard</button>}/></div>
    :view==="grid"?<div className="grid-cards pg2">{P.slice.map(d=><LibraryCard key={d.id} title={d.name} onOpen={()=>open(d)}
        tags={<><TypeTag type="tableau"/><span className="tag">{d.category}</span><span className="tag">{(d.fmt||"pdf").toUpperCase()}</span></>}
        desc={d.description}
        meta={<><span className="mono trunc" style={{maxWidth:"100%"}} title={d.view_url}>{viewPath(d.view_url)}</span><span>{d.schedule_count||0} active schedule{d.schedule_count===1?"":"s"}</span>{(d.additional_urls||[]).length>0&&<span>+{d.additional_urls.length} view{d.additional_urls.length>1?"s":""}</span>}{O.showOwner&&d.owner&&<span>{d.owner.name}</span>}</>}
        status={lastLine(d,"sent")}
        actions={<><button className="btn btn-primary btn-sm" style={{flex:1}} onClick={()=>setSend(d)}><Icon name="mail" size={13}/>Test send</button>
          {O.isMine(d)?<button className="btn btn-sm" style={{flex:1}} onClick={()=>setEdit(d)}><Icon name="edit" size={13}/>Edit</button>:<button className="btn btn-sm" style={{flex:1}} onClick={()=>setDetail(d)}>Details</button>}
          <button className="btn btn-sm btn-icon" title="Schedule it" aria-label="Schedule it" onClick={()=>go("schedules",{action:"new",type:"tableau",dashboardId:d.id})}><Icon name="schedules" size={14}/></button></>}/>)}</div>
    :<div className="card pg2"><div className="tbl-wrap"><table className="tbl">
      <thead><tr><th>Name</th><th>Category</th><th>Format</th>{O.showOwner&&<th>Owner</th>}<th>Schedules</th><th>Last sent</th><th>Status</th><th className="actions"><span className="sr">Actions</span></th></tr></thead>
      <tbody>{P.slice.map(d=><tr key={d.id} className="row" onClick={()=>open(d)}>
        <td className="name">{d.name}{d.description&&<div className="small muted trunc" style={{fontWeight:400,maxWidth:340}}>{d.description}</div>}</td>
        <td>{d.category}</td><td>{(d.fmt||"pdf").toUpperCase()}</td>{O.showOwner&&<td>{d.owner?.name||"—"}</td>}<td>{d.schedule_count||0} active</td>
        <td>{d.last_run?fmtWhen(d.last_run):<span className="muted">Never</span>}</td><td>{d.last_status?<StatusChip status={d.last_status}/>:<span className="muted">—</span>}</td>
        <td className="actions" onClick={e=>e.stopPropagation()}><button className="btn btn-primary btn-sm" onClick={()=>setSend(d)}>Test send</button>{O.isMine(d)?<button className="btn btn-sm" onClick={()=>setEdit(d)}>Edit</button>:<button className="btn btn-sm" onClick={()=>setDetail(d)}>Details</button>}</td>
      </tr>)}</tbody></table></div></div>}
    <Pagination page={P.page} total={P.total} onPage={P.setPage}/>
    {add&&<DashboardFormModal onSave={r=>{setAdd(false);toast(`“${r.name}” registered`);load();}} onClose={()=>setAdd(false)}/>}
    {edit&&<DashboardFormModal dashboard={edit} onSave={()=>{setEdit(null);toast("Changes saved");load();}} onClose={()=>setEdit(null)} onDelete={del}/>}
    {detail&&<AdminDetailModal item={detail} type="dashboard" onClose={()=>setDetail(null)} onChanged={load}/>}
    {send&&<TestSendModal dashboard={send} user={user} onClose={()=>setSend(null)}/>}
  </div>;
}

// ─── SharePoint sites ─────────────────────────────────────────────────────────
function SiteActivity({site}){
  const [a,setA]=useState(null);const [err,setErr]=useState("");
  useEffect(()=>{api.spSiteActivity(site.id).then(setA).catch(e=>setErr(e.message));},[site.id]);
  if(err)return <div className="small" style={{color:"var(--badText)"}}>{err}</div>;
  if(!a)return <div className="small muted" style={{display:"flex",gap:8,alignItems:"center"}}><Spinner size={12}/>Loading activity…</div>;
  return <div className="drop" style={{display:"grid",gridTemplateColumns:"minmax(0,1fr) minmax(0,1.4fr)",gap:18}}>
    <div>
      <div className="kv" style={{marginBottom:12}}>
        <div><div className="k">Uploads this month</div><div className="v">{a.uploads_this_month}</div></div>
        <div><div className="k">Schedules using it</div><div className="v">{a.schedule_count}</div></div>
      </div>
      <div className="lbl">Folders used</div>
      {a.folders.length?a.folders.map(f=><div key={f} className="small mono" style={{display:"flex",gap:6,alignItems:"center",padding:"3px 0",color:"var(--text2)"}}><Icon name="folder" size={13}/>{f}</div>):<div className="small muted">No folders yet</div>}
    </div>
    <div>
      <div className="lbl">Recent uploads</div>
      {a.recent.length?a.recent.map(r=><div key={r.id} style={{display:"flex",alignItems:"center",gap:10,padding:"5px 0",borderBottom:"1px solid var(--border)"}}>
        <StatusChip status={r.status}/><span className="trunc" style={{flex:1,fontSize:13}}>{r.name}</span><span className="small muted" style={{whiteSpace:"nowrap"}}>{fmtWhen(r.started_at)}</span>
      </div>):<div className="small muted">Nothing uploaded yet</div>}
    </div>
  </div>;
}
function SharepointSites({params}){
  const {toast,confirm,go}=useApp();
  const [items,setItems]=useState(()=>peek("/sharepoint/sites/",[]));const [loading,setLoading]=useState(true);
  const [search,setSearch]=useState("");const [typeF,setTypeF]=useState("all");
  const [modal,setModal]=useState(null);const [open,setOpen]=useState(null);const [testing,setTesting]=useState({});
  const load=async()=>{setLoading(true);try{setItems(await api.getSpSites());}catch(e){toast(e.message,"bad");}finally{setLoading(false);}};
  useEffect(()=>{load();},[]);
  const O=useOwnerScope(items,params);
  useEffect(()=>{if(params?.action==="register")setModal({});if(params?.openId)setOpen(params.openId);},[params]);
  const test=async s=>{setTesting(t=>({...t,[s.id]:"running"}));
    try{await api.testSpSite(s.id);setTesting(t=>({...t,[s.id]:"ok"}));toast(`Connected to ${s.name}`);}
    catch(e){setTesting(t=>({...t,[s.id]:"fail"}));toast("Connection failed: "+e.message,"bad");}};
  const del=async s=>{if(!await confirm({title:"Delete this site?",body:`“${s.name}” will be removed. Schedules that upload to it will stop working.`,confirmLabel:"Delete site",danger:true}))return;
    try{await api.deleteSpSite(s.id);toast("Site deleted");load();}catch(e){toast(e.message,"bad");}};
  const q=search.toLowerCase();
  const filtered=items.filter(s=>O.pass(s)&&(typeF==="all"||(s.site_type||"internal")===typeF)&&(s.name.toLowerCase().includes(q)||s.site_url.toLowerCase().includes(q)));
  const cols=O.showOwner?8:7;
  return <div style={{display:"flex",flexDirection:"column",gap:18}}>
    <div className="toolbar pg">
      <SearchBox value={search} onChange={setSearch} placeholder="Search sites…"/>
      {O.controls}
      <select className="field lib-filter" value={typeF} onChange={e=>setTypeF(e.target.value)} aria-label="Site type"><option value="all">All site types</option><option value="internal">Internal</option><option value="external">External</option></select>
      <span className="spacer"/>
      <button className="btn btn-primary lib-add" onClick={()=>setModal({})}><Icon name="plus" size={15}/>Register site</button>
    </div>
    <div className="card pg2"><div className="tbl-wrap"><table className="tbl">
      <thead><tr><th style={{width:36}}><span className="sr">Expand</span></th><th>Site</th><th>Type</th>{O.showOwner&&<th>Owner</th>}<th>Schedules</th><th>Added</th><th>Status</th><th className="actions"><span className="sr">Actions</span></th></tr></thead>
      {loading&&!items.length?<SkelRows rows={4} cols={cols}/>:<tbody>
        {filtered.length===0&&<tr><td colSpan={cols}><Empty title="No SharePoint sites found" sub={items.length?"Try a different search or filter":"Register a site to start uploading files"} icon="sharepoint"/></td></tr>}
        {filtered.map(s=>{const ex=open===s.id;const t=testing[s.id];return <React.Fragment key={s.id}>
          <tr className={"row"+(ex?" sel":"")} onClick={()=>setOpen(ex?null:s.id)} aria-expanded={ex}>
            <td><Icon name="chevR" size={15} style={{color:"var(--text3)",transition:"transform .2s",transform:`rotate(${ex?90:0}deg)`}}/></td>
            <td className="name">{s.name}<div className="small muted mono trunc" style={{fontWeight:400,maxWidth:380}}>{s.site_url}</div></td>
            <td><span className="tag">{(s.site_type||"internal")==="internal"?"Internal":"External"}</span></td>
            {O.showOwner&&<td>{s.owner?.name||s.created_by_name||"—"}</td>}
            <td>{s.schedule_count} active</td><td>{fmtDateShort(s.created_at)}</td>
            <td><StatusChip status={s.is_active?"active":"inactive"} label={s.is_active?"Active":"Inactive"}/></td>
            <td className="actions" onClick={e=>e.stopPropagation()}>
              <button className="btn btn-sm" onClick={()=>test(s)} disabled={!s.is_active||t==="running"} title={!s.is_active?"Site is inactive":"Check that Conductor can reach this site"} style={t==="ok"?{color:"var(--okText)"}:t==="fail"?{color:"var(--badText)"}:undefined}>
                {t==="running"?<><Spinner size={12}/>Testing…</>:t==="ok"?<><Icon name="check" size={13}/>Connected</>:t==="fail"?"Failed · retry":"Test connection"}</button>
              {O.isMine(s)||O.admin?<><button className="btn btn-sm btn-icon" onClick={()=>setModal(s)} aria-label="Edit site" title="Edit"><Icon name="edit" size={14}/></button>
              <button className="btn btn-sm btn-icon" onClick={()=>del(s)} aria-label="Delete site" title="Delete" style={{color:"var(--badText)"}}><Icon name="trash" size={14}/></button></>:null}
            </td>
          </tr>
          {ex&&<tr className="drop"><td colSpan={cols} style={{background:"var(--surface2)",padding:"16px 22px"}}>
            <SiteActivity site={s}/>
            <div style={{marginTop:12}}><button className="btn btn-sm" onClick={()=>go("schedules",{action:"new",type:"sharepoint",siteId:s.id})}><Icon name="plus" size={13}/>New upload schedule</button></div>
          </td></tr>}
        </React.Fragment>;})}
      </tbody>}
    </table></div></div>
    {modal&&<SpSiteModal site={modal.id?modal:null} onSave={()=>{setModal(null);toast("Site saved");load();}} onClose={()=>setModal(null)}/>}
  </div>;
}