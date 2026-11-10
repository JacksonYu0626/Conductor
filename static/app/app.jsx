// ─── app.jsx ─────────────────────────────────────────────────────────────────
// App shell: session, theme, navigation, running jobs, toasts, quick search.

function resolveTheme(pref){
  if(pref==="system")return window.matchMedia&&window.matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light";
  return pref==="dark"?"dark":"light";
}

function App(){
  const [user,setUser]=useState(null);const [booting,setBooting]=useState(true);
  const [pendingUser,setPendingUser]=useState(null);const [pendingDest,setPendingDest]=useState(null);const [transitioning,setTransitioning]=useState(false);const [tileRect,setTileRect]=useState(null);
  const [page,setPage]=useState(()=>{const p=lsGet("cond_page","summary");return PAGES[p]?p:"summary";});
  const [params,setParams]=useState(null);
  const [collapsed,setCollapsedS]=useState(()=>lsGet("sp_collapsed","false")==="true");
  const [themePref,setThemePrefS]=useState(()=>lsGet("cond_theme","light"));
  const [theme,setTheme]=useState(()=>resolveTheme(lsGet("cond_theme","light")));
  const [running,setRunning]=useState([]);
  // Bumps whenever a run finishes, so open pages can refresh themselves.
  const [runsTick,setRunsTick]=useState(0);const prevRunIds=useRef(new Set());
  const [toasts,setToasts]=useState([]);
  const [confirmCfg,setConfirmCfg]=useState(null);
  const [palette,setPalette]=useState(false);
  const [testRun,setTestRun]=useState(null);
  // Link from a share email: /?schedule=ID opens Schedules on that schedule (after sign-in if needed)
  const linkDest=useRef((()=>{try{const q=new URLSearchParams(window.location.search);const id=parseInt(q.get("schedule"),10);
    if(id){window.history.replaceState(null,"",window.location.pathname);return {page:"schedules",params:{openId:id}};}}catch(e){}return null;})());
  // Version: what the server runs vs this page (UI_VERSION). A newer server shows a Refresh card;
  // "Later" hides it until the next version. What's new shows a dot until opened once per version.
  const [serverVer,setServerVer]=useState(null);const [whatsNew,setWhatsNew]=useState(false);
  const [wnSeen,setWnSeen]=useState(()=>lsGet("cond_whatsnew_seen",""));
  const [verLater,setVerLater]=useState(()=>lsGet("cond_ver_later",""));
  useEffect(()=>{const f=()=>api.appVersion().then(setServerVer).catch(()=>{});f();
    const t=setInterval(()=>{if(!document.hidden)f();},5*60e3);return()=>clearInterval(t);},[]);
  const openWhatsNew=()=>{setWhatsNew(true);setWnSeen(UI_VERSION);lsSet("cond_whatsnew_seen",UI_VERSION);};
  const newer=serverVer?.version&&verCmp(serverVer.version,UI_VERSION)>0&&verLater!==serverVer.version;
  // How many schedules were shared with me that I haven't opened yet (sidebar count)
  const [newShares,setNewShares]=useState(0);

  useEffect(()=>{document.documentElement.setAttribute("data-theme",theme);},[theme]);
  useEffect(()=>{
    if(themePref!=="system"||!window.matchMedia)return;
    const mq=window.matchMedia("(prefers-color-scheme: dark)");const h=()=>setTheme(mq.matches?"dark":"light");
    mq.addEventListener?mq.addEventListener("change",h):mq.addListener(h);
    return()=>{mq.removeEventListener?mq.removeEventListener("change",h):mq.removeListener(h);};
  },[themePref]);
  useEffect(()=>{
    const t=lsGet("sp_token","");
    if(t)api.getMe().then(setUser).catch(()=>{try{localStorage.removeItem("sp_token");}catch(e){}}).finally(()=>setBooting(false));
    else setBooting(false);
  },[]);

  const refreshRunning=useCallback(()=>{if(!lsGet("sp_token",""))return;api.getRunning().then(rows=>{
    const ids=new Set(rows.map(r=>r.id));
    const finished=[...prevRunIds.current].some(id=>!ids.has(id));
    prevRunIds.current=ids;setRunning(rows);
    if(finished)setRunsTick(t=>t+1);
  }).catch(()=>{});},[]);
  useEffect(()=>{if(user)refreshRunning();},[user]);
  useEffect(()=>{if(user&&linkDest.current){const d=linkDest.current;linkDest.current=null;go(d.page,d.params);}},[user]);
  useEffect(()=>{
    if(!user)return;
    const count=list=>setNewShares(newSharedSchedules(user,list).length);
    const fetch_=()=>api.getSchedules().then(count).catch(()=>{});fetch_();
    const t=setInterval(()=>{if(!document.hidden)fetch_();},60000);
    const h=()=>count(peek("/schedules/",[]));window.addEventListener("cond-shares-changed",h);
    return()=>{clearInterval(t);window.removeEventListener("cond-shares-changed",h);};
  },[user]);
  useInterval(()=>{if(user&&!document.hidden)refreshRunning();},page==="schedules"?3000:running.length?5000:15000,[user,running.length,page]);

  useEffect(()=>{
    const h=e=>{if((e.ctrlKey||e.metaKey)&&(e.key==="k"||e.key==="K")){if(!user)return;e.preventDefault();setPalette(p=>!p);}};
    document.addEventListener("keydown",h);return()=>document.removeEventListener("keydown",h);
  },[user]);

  const toast=useCallback((msg,kind)=>{const id=Math.random();setToasts(t=>[...t,{id,msg,kind}]);setTimeout(()=>setToasts(t=>t.filter(x=>x.id!==id)),kind==="bad"?5000:2800);},[]);
  const confirm=useCallback(cfg=>new Promise(res=>setConfirmCfg({...cfg,res})),[]);
  const go=useCallback((p,prm)=>{setPage(p);lsSet("cond_page",p);setParams(prm?{...prm,_t:Date.now()}:null);window.scrollTo(0,0);},[]);
  const setCollapsed=v=>{setCollapsedS(v);lsSet("sp_collapsed",String(v));};
  const setThemePref=v=>{setThemePrefS(v);lsSet("cond_theme",v);setTheme(resolveTheme(v));toast("Default theme saved");};
  const toggleTheme=()=>{const n=theme==="dark"?"light":"dark";setTheme(n);if(themePref!=="system"){setThemePrefS(n);lsSet("cond_theme",n);}};
  const logout=()=>{clearGetCache();try{localStorage.removeItem("sp_token");localStorage.removeItem("cond_page");}catch(e){}setUser(null);setRunning([]);setPage("summary");};
  const stopRun=useCallback(async r=>{
    const name=r.name||r.schedule_name||r.script_name||"this run";
    const ok=await new Promise(res=>setConfirmCfg({title:"Stop this run?",body:`“${name}” will be stopped and marked as stopped in Run history.`,confirmLabel:"Stop run",danger:true,res}));
    if(!ok)return false;
    try{
      if(r.log_type==="tableau"||r.log_type==="sharepoint"||!r.script_id)await api.stopLog(r.id);
      else await api.stopScript(r.script_id);
      toast(`Stopped “${name}”`);setTimeout(refreshRunning,600);return true;
    }catch(e){toast("Could not stop: "+e.message,"bad");return false;}
  },[]);
  const openTestRun=useCallback((script,start)=>setTestRun({script,start:!!start,key:Date.now()}),[]);
  const openNew=kind=>{
    if(kind==="script")go("scripts",{action:"register"});
    else if(kind==="dashboard")go("dashboards",{action:"register"});
    else if(kind==="site")go("sp_sites",{action:"register"});
    else go("schedules",{action:"new",type:"script"});
  };

  if(booting)return <div className="boot"><Spinner size={26}/></div>;
  const ctx={user,go,toast,confirm,running,runsTick,refreshRunning,stopRun,openTestRun,openNew,theme,themePref,setThemePref,toggleTheme,logout};
  const Page={summary:Summary,logs:RunHistory,schedules:Schedules,scripts:Scripts,dashboards:Dashboards,sp_sites:SharepointSites,users:Users,feedback:Feedback,profile:Profile}[page]||Summary;
  return <AppCtx.Provider value={ctx}>
    {!user&&<Login onLogin={(u,pg,prm,rect)=>{setPendingUser(u);setPendingDest({page:pg||"summary",params:prm||null});setTileRect(rect||null);setTransitioning(true);}}/>}
    {user&&<div className="shell">
      <Sidebar page={page} go={go} user={user} onLogout={logout} collapsed={collapsed} setCollapsed={setCollapsed} badges={{schedules:newShares}}
        ver={{server:serverVer?.version,started:serverVer?.started_at,unseen:verCmp(wnSeen||"0",UI_VERSION)<0,onWhatsNew:openWhatsNew}}/>
      <div className="main-col">
        <Header page={page} onOpenSearch={()=>setPalette(true)} theme={theme} toggleTheme={toggleTheme}/>
        {newer&&<div className="ver-card" role="status">
          <div className="ver-card-ic" aria-hidden="true">↻</div>
          <div style={{flex:1,minWidth:0}}><b>A new version of Conductor is ready ({serverVer.version}).</b><div className="small muted">Refresh the page to use it. Nothing you're working on is lost; running jobs keep running.</div></div>
          <button type="button" className="btn btn-primary btn-sm" onClick={()=>window.location.reload()}>Refresh</button>
          <button type="button" className="btn btn-sm" onClick={()=>{setVerLater(serverVer.version);lsSet("cond_ver_later",serverVer.version);}}>Later</button>
        </div>}
        <main className="content" key={page}><Page params={params}/></main>
        {whatsNew&&<WhatsNewModal onClose={()=>setWhatsNew(false)}/>}
      </div>
    </div>}
    {transitioning&&<DiveTransition rect={tileRect} onAppReady={()=>{setUser(pendingUser);go(pendingDest?.page||"summary",pendingDest?.params);setPendingUser(null);}} onDone={()=>setTransitioning(false)}/>}
    {palette&&user&&<QuickSearch onClose={()=>setPalette(false)}/>}
    {testRun&&user&&<TestRunModal key={testRun.key} script={testRun.script} start={testRun.start} onClose={()=>setTestRun(null)}/>}
    {confirmCfg&&<ConfirmDialog cfg={confirmCfg} onDone={ok=>{confirmCfg.res(ok);setConfirmCfg(null);}}/>}
    <Toasts items={toasts}/>
  </AppCtx.Provider>;
}

ReactDOM.createRoot(document.getElementById("root")).render(<App/>);