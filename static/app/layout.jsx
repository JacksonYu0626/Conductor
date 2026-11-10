// ─── layout.jsx ──────────────────────────────────────────────────────────────
// Fixed sidebar, sticky header (search, running indicator, theme), quick search.

const PAGES={
  summary:{title:"Summary",group:"Overview",icon:"summary"},
  logs:{title:"Run history",group:"Overview",icon:"history"},
  schedules:{title:"Schedules",group:"Automate",icon:"schedules"},
  scripts:{title:"Scripts",group:"Library",icon:"scripts"},
  dashboards:{title:"Dashboards",group:"Library",icon:"dashboards"},
  sp_sites:{title:"SharePoint sites",group:"Library",icon:"sharepoint"},
  users:{title:"Users",group:"Workspace",icon:"users"},
  feedback:{title:"Feedback",group:"Workspace",icon:"feedback"},
  profile:{title:"My profile",group:"Workspace",icon:"user"},
};
const NAV=[["Overview",["summary","logs"]],["Automate",["schedules"]],["Library",["scripts","dashboards","sp_sites"]],["Workspace",["users","feedback"]]];

function Sidebar({page,go,user,onLogout,collapsed,setCollapsed,badges={},ver}){
  const lab=collapsed?"Expand sidebar":"Collapse sidebar";
  return <nav aria-label="Main" className={"side"+(collapsed?" collapsed":"")}>
    <div className="logo-row">
      <LogoMark/>
      {!collapsed&&<span className="brand">Conductor</span>}
      <button type="button" className="collapse-btn" onClick={()=>setCollapsed(!collapsed)} aria-label={lab} title={lab}><Icon name={collapsed?"chevR":"chevL"} size={16}/></button>
    </div>
    {NAV.map(([grp,ids])=><React.Fragment key={grp}>
      <div className="nav-head">{grp}</div>
      {ids.map(id=><button key={id} type="button" className={"nav-btn"+(page===id?" on":"")} onClick={()=>go(id)} title={collapsed?PAGES[id].title:undefined} aria-current={page===id?"page":undefined}>
        <Icon name={PAGES[id].icon} size={18}/>{!collapsed&&<span>{PAGES[id].title}</span>}
        {badges[id]>0&&<span className={"nav-badge"+(collapsed?" dot":"")} title={`${badges[id]} shared with you, not opened yet`}>{collapsed?"":badges[id]}</span>}
      </button>)}
    </React.Fragment>)}
    <div className="side-foot">
      <button type="button" className={"nav-btn"+(page==="profile"?" on":"")} onClick={()=>go("profile")} title="My profile">
        <Avatar name={user?.name} size={30}/>
        {!collapsed&&<span style={{display:"flex",flexDirection:"column",minWidth:0}}><span className="trunc" style={{fontSize:13,fontWeight:600,color:"var(--text)"}}>{user?.name}</span><span style={{fontSize:12,color:"var(--text3)",textTransform:"capitalize"}}>{user?.role}</span></span>}
      </button>
      {/* Version + What's new, under the account */}
      {ver&&!collapsed&&<div className="ver-row" title={`Version ${ver.server||UI_VERSION}${ver.started?` · server started ${ver.started.replace("T"," ")}`:""}`}>
        <span className="ver-label">Conductor {UI_VERSION}</span>
        <button type="button" className="ver-link" onClick={ver.onWhatsNew}>{ver.unseen&&<span className="ver-dot" aria-label="New"/>}What's new</button>
      </div>}
      {ver&&!collapsed&&ver.server&&verCmp(ver.server,UI_VERSION)<0&&<div className="ver-old">Server on {ver.server}: restart Conductor</div>}
      {ver&&collapsed&&<button type="button" className="nav-btn ver-mini" onClick={ver.onWhatsNew} title={`Conductor ${UI_VERSION} · What's new`}><Icon name="info" size={16}/>{ver.unseen&&<span className="nav-badge dot"/>}</button>}
    </div>
  </nav>;
}

function runProgress(r,now){
  const el=Math.max(0,(now-toDate(r.started_at).getTime())/1000);
  if(!r.timeout_sec)return {el,pct:null,warn:false,text:`${el<1?"0s":msStr(el*1000)} so far · no time limit`};
  const pct=Math.min(99,el/r.timeout_sec*100);const warn=pct>75;
  return {el,pct,warn,text:`${msStr(el*1000)} of ${secStr(r.timeout_sec)} max${warn?" · near limit":""}`};
}
function useNow(ms=1000){const [n,setN]=useState(Date.now());useInterval(()=>setN(Date.now()),ms);return n;}

function RunningPanel({onClose}){
  const {running,stopRun,openTestRun,go}=useApp();
  const now=useNow();
  return <div className="popover" role="dialog" aria-label="Running now" style={{top:62,right:28,width:400,maxWidth:"calc(100% - 32px)",padding:14,display:"flex",flexDirection:"column",gap:10}}>
    <div style={{display:"flex",justifyContent:"space-between",alignItems:"center"}}><span style={{fontWeight:600}}>Running now</span><button className="link-btn" style={{fontSize:13}} onClick={()=>{onClose();go("schedules");}}>Open schedules</button></div>
    {running.length===0&&<p className="small muted" style={{margin:0}}>Nothing is running right now.</p>}
    {running.map(r=>{const p=runProgress(r,now);const isTest=r.is_manual&&!r.schedule_id&&r.log_type==="script";
      return <div key={r.id} style={{display:"flex",flexDirection:"column",gap:6,padding:10,borderRadius:10,background:"var(--surface2)"}}>
        <div style={{display:"flex",justifyContent:"space-between",alignItems:"flex-start",gap:10}}>
          <div style={{minWidth:0}}><div className="trunc" style={{fontWeight:600,fontSize:13}}>{r.name||r.schedule_name}</div><div className="small muted">{isTest?"Test run":r.is_manual?"Run now":"Scheduled run"}{r.triggered_by_name?` · ${r.triggered_by_name}`:""}</div></div>
          {r.can_stop!==false&&<button className="btn btn-danger btn-sm" onClick={()=>stopRun(r)}>Stop</button>}
        </div>
        <div className={"progress"+(p.warn?" warn":"")+(p.pct==null?" indet":"")}><div style={{width:(p.pct||0)+"%"}}/></div>
        <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",gap:8}}>
          <span className="small muted">{p.text}</span>
          {r.log_type==="script"&&r.script_id&&<button className="link-btn" style={{fontSize:12.5}} onClick={()=>{onClose();openTestRun({id:r.script_id,name:r.name});}}>View output</button>}
        </div>
      </div>;})}
  </div>;
}

function Header({page,onOpenSearch,theme,toggleTheme}){
  const {running}=useApp();
  const [panel,setPanel]=useState(false);
  const runRef=useRef(null);useOutside(runRef,()=>setPanel(false),panel);
  const n=running.length;const P=PAGES[page]||PAGES.summary;
  return <header className="topbar">
    <div className="topbar-in">
      <div style={{display:"flex",flexDirection:"column",gap:2,minWidth:0}}><span className="crumb">{P.group}</span><span className="page-title">{P.title}</span></div>
      <button type="button" onClick={onOpenSearch} aria-haspopup="dialog" className="field" style={{marginLeft:"auto",flex:"0 1 300px",width:"auto",display:"flex",alignItems:"center",gap:8,color:"var(--text3)",cursor:"pointer",textAlign:"left",fontSize:13}}>
        <Icon name="search" size={15}/><span style={{flex:1}}>Search anything</span><kbd>Ctrl K</kbd>
      </button>
      <div ref={runRef} style={{display:"contents"}}>
      <button type="button" className="btn" onClick={()=>setPanel(p=>!p)} aria-expanded={panel} aria-label={`${n} running`}
        style={n?{borderColor:"var(--accent)",color:"var(--accentText)",background:"var(--accentSoft)",fontWeight:600}:{color:"var(--text2)"}}>
        <span className={"dot8"+(n?" pulse":"")} style={{background:n?"var(--accent)":"var(--text3)"}}/>{n?`${n} running`:"Idle"}
      </button>
      {panel&&<RunningPanel onClose={()=>setPanel(false)}/>}
      </div>
      <button type="button" className="btn btn-icon" onClick={toggleTheme} aria-label={theme==="dark"?"Switch to light mode":"Switch to dark mode"} title={theme==="dark"?"Switch to light mode":"Switch to dark mode"} style={{color:"var(--text2)"}}>
        <span key={theme} className="pop" style={{display:"flex"}}><Icon name={theme==="dark"?"sun":"moon"} size={17}/></span>
      </button>
    </div>
  </header>;
}

// ─── Quick search (Ctrl+K) ────────────────────────────────────────────────────
function QuickSearch({onClose}){
  const {go,user,toggleTheme,logout,openNew}=useApp();
  const [q,setQ]=useState("");const [idx,setIdx]=useState(0);
  const [data,setData]=useState({scripts:[],dashboards:[],schedules:[],sites:[],logs:[]});const [loading,setLoading]=useState(true);
  const admin=isAdminUser(user);
  useEffect(()=>{
    Promise.all([api.getScripts().catch(()=>[]),api.getDashboards().catch(()=>[]),api.getSchedules().catch(()=>[]),api.getSpSites().catch(()=>[]),api.getLogs({limit:8}).catch(()=>[])])
      .then(([scripts,dashboards,schedules,sites,logs])=>{
        // Admins get everything from the API; keep the palette to their own items unless they search by name.
        const mine=x=>!admin||!x.owner||x.owner.id===user.id;
        setData({scripts:scripts.filter(mine),dashboards:dashboards.filter(mine),schedules:schedules.filter(s=>!admin||!s.owner_email||s.owner_email===user.email).filter(s=>!(s.name||"").startsWith("[Ad-hoc]")),sites:sites.filter(mine),logs:logs.slice(0,8)});
      }).finally(()=>setLoading(false));
  },[]);
  const ql=q.trim().toLowerCase();const m=s=>!ql||(s||"").toLowerCase().includes(ql);
  const groups=[
    ["Pages",Object.entries(PAGES).filter(([id,p])=>m(p.title)).map(([id,p])=>({label:p.title,icon:p.icon,sub:p.group,run:()=>go(id)}))],
    ["Actions",[
      {label:"Register a script",icon:"plus",run:()=>openNew("script")},
      {label:"Register a dashboard",icon:"plus",run:()=>openNew("dashboard")},
      {label:"New schedule",icon:"schedules",run:()=>openNew("schedule")},
      {label:"Register a SharePoint site",icon:"plus",run:()=>openNew("site")},
      {label:"Send feedback",icon:"feedback",run:()=>go("feedback")},
      {label:"Switch light / dark mode",icon:"moon",run:()=>toggleTheme()},
      {label:"Sign out",icon:"logout",run:()=>logout()},
    ].filter(a=>m(a.label))],
    ["Scripts",data.scripts.filter(s=>m(s.name)||m(s.category)).slice(0,6).map(s=>({label:s.name,icon:"scripts",sub:s.category,run:()=>go("scripts",{openId:s.id})}))],
    ["Dashboards",data.dashboards.filter(d=>m(d.name)||m(d.category)).slice(0,6).map(d=>({label:d.name,icon:"dashboards",sub:d.category,run:()=>go("dashboards",{openId:d.id})}))],
    ["Schedules",data.schedules.filter(s=>m(s.name)||m(s.script_name)||m(s.dashboard_name)).slice(0,6).map(s=>({label:s.name||s.script_name||s.dashboard_name,icon:"schedules",sub:TYPE_LABEL[s.schedule_type||"script"],run:()=>go("schedules",{openId:s.id})}))],
    ["SharePoint sites",data.sites.filter(s=>m(s.name)||m(s.site_url)).slice(0,5).map(s=>({label:s.name,icon:"sharepoint",sub:s.site_type==="external"?"External":"Internal",run:()=>go("sp_sites",{openId:s.id})}))],
    ["Recent runs",data.logs.filter(l=>m(l.script_name)||m(l.schedule_name)).slice(0,5).map(l=>({label:l.script_name||l.schedule_name,icon:"history",sub:`${STATUS_CFG[l.status]?.[1]||l.status} · ${fmtWhen(l.started_at)}`,run:()=>go("logs",{logId:l.id})}))],
  ].filter(([,items])=>items.length);
  const flat=groups.flatMap(([,items])=>items);
  useEffect(()=>{setIdx(0);},[q]);
  const pick=it=>{onClose();it.run();};
  const onKey=e=>{
    if(e.key==="ArrowDown"){e.preventDefault();setIdx(i=>Math.min(flat.length-1,i+1));}
    else if(e.key==="ArrowUp"){e.preventDefault();setIdx(i=>Math.max(0,i-1));}
    else if(e.key==="Enter"){e.preventDefault();if(flat[idx])pick(flat[idx]);}
    else if(e.key==="Escape"){onClose();}
  };
  const listRef=useRef(null);
  useEffect(()=>{const el=listRef.current?.querySelector(".pal-item.on");if(el)el.scrollIntoView({block:"nearest"});},[idx]);
  let k=-1;
  return <Portal>
    <div className="drawer-ov" style={{zIndex:1000}} onClick={onClose}/>
    <div className="palette" role="dialog" aria-label="Quick search">
      <div style={{position:"relative"}}><Icon name="search" size={18} style={{position:"absolute",left:17,top:18,color:"var(--text3)"}}/>
        <input autoFocus value={q} onChange={e=>setQ(e.target.value)} onKeyDown={onKey} placeholder="Search pages, actions, scripts, dashboards, schedules…" aria-label="Search"/></div>
      <div ref={listRef} style={{overflowY:"auto",paddingBottom:8}}>
        {groups.map(([g,items])=><div key={g}><div className="pal-group">{g}</div>
          {items.map(it=>{k++;const my=k;return <div key={g+my} className={"pal-item"+(my===idx?" on":"")} onMouseEnter={()=>setIdx(my)} onClick={()=>pick(it)}>
            <Icon name={it.icon} size={16}/><span className="trunc">{it.label}</span>{it.sub&&<span className="sub">{it.sub}</span>}
          </div>;})}
        </div>)}
        {!flat.length&&!loading&&<div className="empty" style={{padding:28}}>No results for "{q}"</div>}
        {loading&&<div className="small muted" style={{padding:"8px 18px",display:"flex",gap:8,alignItems:"center"}}><Spinner size={12}/>Loading your items…</div>}
      </div>
      <div className="small muted" style={{borderTop:"1px solid var(--border)",padding:"8px 18px",display:"flex",gap:14}}><span><kbd>↑</kbd> <kbd>↓</kbd> move</span><span><kbd>Enter</kbd> open</span><span><kbd>Esc</kbd> close</span>{admin&&<span style={{marginLeft:"auto"}}>Shows your own items</span>}</div>
    </div>
  </Portal>;
}