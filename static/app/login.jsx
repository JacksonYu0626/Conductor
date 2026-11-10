// ─── login.jsx ───────────────────────────────────────────────────────────────
// Sign-in (Global Security Windows detection, or manual username in dev mode)
// followed by the welcome screen. Matches the approved "Pulse" prototype.

// The ∞ draws itself in. It waits a moment first so the page has finished
// loading (fonts, first requests) — otherwise the browser is busy and the
// drawing skips frames and looks rushed.
function DrawnLogo({size=72,color="var(--accent)",sw=1.8,delay=0.5,duration=1.6}){
  const st={strokeDasharray:1,strokeDashoffset:1,animation:`logoDraw ${duration}s ${delay}s cubic-bezier(.65,0,.35,1) both`,willChange:"stroke-dashoffset"};
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={sw} strokeLinecap="round" strokeLinejoin="round" shapeRendering="geometricPrecision" aria-hidden="true">
    <path pathLength="1" style={st} d="M12 12c-2-2.5-4-4-6-4a4 4 0 0 0 0 8c2 0 4-1.5 6-4z"/>
    <path pathLength="1" style={st} d="M12 12c2 2.5 4 4 6 4a4 4 0 0 0 0-8c-2 0-4 1.5-6 4z"/>
  </svg>;
}
function StepRow({state,label,strong}){
  return <div style={{display:"flex",alignItems:"center",gap:10}}>
    {state==="done"&&<span className="pop" style={{width:20,height:20,borderRadius:"50%",background:"var(--okSoft)",color:"var(--okText)",display:"flex",alignItems:"center",justifyContent:"center",flexShrink:0}}><Icon name="check" size={12} sw={3}/></span>}
    {state==="busy"&&<span className="spinner" style={{width:16,height:16,margin:2}}/>}
    {state==="wait"&&<span style={{width:20,height:20,borderRadius:"50%",border:"2px dashed var(--border2)",flexShrink:0}}/>}
    {state==="fail"&&<span className="pop" style={{width:20,height:20,borderRadius:"50%",background:"var(--badSoft)",color:"var(--badText)",display:"flex",alignItems:"center",justifyContent:"center",flexShrink:0}}><Icon name="x" size={12} sw={3}/></span>}
    <span style={{color:state==="done"?"var(--text)":state==="fail"?"var(--badText)":"var(--text3)",fontWeight:strong&&state==="done"?600:400}}>{label}</span>
  </div>;
}

function Login({onLogin}){
  const [devMode,setDevMode]=useState(false);
  const [gsUser,setGsUser]=useState(null);
  const [step,setStep]=useState(0);          // 0 detecting · 1 checking AD · 3 ready
  const [failed,setFailed]=useState(false);
  const [manualSam,setManualSam]=useState("");
  const [err,setErr]=useState("");
  const [loading,setLoading]=useState(false);
  const [welcome,setWelcome]=useState(null);   // login response once signed in

  useEffect(()=>{
    let live=true;const pause=ms=>new Promise(r=>setTimeout(r,ms));
    (async()=>{
      try{
        const {dev_mode}=await api.devMode();
        if(!live)return;
        setDevMode(dev_mode);
        if(dev_mode){setStep(3);return;}
        const cfg=await api.gsConfig();
        const r=await fetch(`${cfg.gs_base_url}/security/auth?appID=${cfg.gs_app_id}`,{credentials:"include"});
        if(!r.ok)throw new Error("GS "+r.status);
        const data=await r.json();
        if(!live)return;
        setStep(1);await pause(450);          // "Checking Active Directory"
        if(!live)return;
        setGsUser(data);setStep(3);
      }catch(e){
        if(!live)return;
        setFailed(true);setErr("Could not detect your Windows session. Make sure you are on the MPM network, then refresh the page.");
      }
    })();
    return()=>{live=false;};
  },[]);

  const sam=(devMode?manualSam:(gsUser?.samAccountName||""))||"";
  const ready=step>=3&&!!sam.trim();
  const submit=async()=>{
    if(!ready||loading)return;
    setLoading(true);setErr("");
    try{const d=await api.login(sam.trim());lsSet("sp_token",d.access_token);setWelcome(d);}
    catch(e){setErr(e.message||"Login failed");}
    finally{setLoading(false);}
  };

  if(welcome)return <Welcome data={welcome} onContinue={(page,params,rect)=>onLogin(welcome.user,page,params,rect)}/>;

  const st=i=>failed&&step===i?"fail":step>i?"done":step===i?"busy":"wait";
  const found=gsUser?`Found: ${gsUser.name||gsUser.samAccountName}${gsUser.department?" · "+gsUser.department:""}`:"Found your account";
  return <div className="boot" style={{padding:"40px 16px"}}>
    <div className="pg" style={{width:"100%",maxWidth:420,display:"flex",flexDirection:"column",alignItems:"center",gap:26}}>
      <DrawnLogo/>
      <div style={{textAlign:"center",display:"flex",flexDirection:"column",gap:6}}>
        <h1 className="display" style={{margin:0,fontSize:30,fontWeight:800,letterSpacing:"-.02em"}}>MPM Conductor</h1>
        <p style={{margin:0,color:"var(--text2)"}}>Automation and reporting for MedPOINT</p>
      </div>
      <div className="card" style={{width:"100%",padding:24,display:"flex",flexDirection:"column",gap:16}}>
        {devMode
          ?<div className="fade" style={{display:"flex",flexDirection:"column",gap:6}}>
            <label htmlFor="sam" className="lbl" style={{margin:0}}>Windows username (dev mode)</label>
            <input id="sam" className="field" value={manualSam} onChange={e=>setManualSam(e.target.value)} onKeyDown={e=>e.key==="Enter"&&submit()} placeholder="jyu" autoFocus/>
            <p className="hint" style={{margin:0}}>Dev mode is on, so Windows detection is skipped.</p>
          </div>
          :<>
            <StepRow state={st(0)} label="Detecting your Windows session"/>
            <StepRow state={failed?(step>=1?"fail":"wait"):st(1)} label="Checking Active Directory"/>
            <StepRow state={step>=3?"done":"wait"} label={found} strong/>
          </>}
        {err&&<div className="note note-bad"><Icon name="warn" size={16}/><div>{err}</div></div>}
        <button type="button" className="btn btn-primary" onClick={submit} disabled={!ready||loading} style={{height:44,fontSize:15}}>
          {loading?<><Spinner size={15} color="#fff"/>Signing in…</>:failed?"Sign in unavailable":step>=3?"Sign in":"Detecting…"}
        </button>
      </div>
      <p className="small muted" style={{margin:0}}>Secured by Active Directory · MPM network</p>
    </div>
  </div>;
}

function WelcomeCard({label,value,sub,color,onClick,delay}){
  const n=useCountUp(value);
  return <button type="button" className="lift" onClick={onClick} style={{background:"var(--surface)",border:"1px solid var(--border)",borderRadius:16,padding:20,display:"flex",flexDirection:"column",gap:4,textAlign:"left",color:"var(--text)",cursor:"pointer",animationDelay:delay}}>
    <span style={{fontSize:13,color:"var(--text2)"}}>{label}</span>
    <span className="display" style={{fontSize:30,fontWeight:800,letterSpacing:"-.02em",color:color||"var(--text)"}}>{n==null?<Spinner size={20}/>:Math.round(n).toLocaleString()}</span>
    <span className="small muted">{sub}</span>
  </button>;
}
function Welcome({data,onContinue:go}){
  const [stats,setStats]=useState(null);
  // Hand the logo tile's position to the transition so the dive starts exactly from it
  const tileRef=useRef(null);
  const onContinue=(page,params)=>{const r=tileRef.current?.getBoundingClientRect();go(page,params,r?{x:r.left,y:r.top,w:r.width,h:r.height}:null);};
  useEffect(()=>{
    const since=addDays(todayStr(),-1);
    Promise.all([api.getLogs({date_from:since}).catch(()=>[]),api.getRunning().catch(()=>[]),api.getSchedules().catch(()=>[])]).then(([logs,running,scheds])=>{
      const ok=logs.filter(l=>l.status==="success").length;const bad=scheds.filter(isFailing).length;
      setStats({total:logs.length,ok,bad,running:running.length,since});
    });
  },[]);
  const first=(data.user?.name||"").split(" ")[0]||"there";
  const s=stats;
  return <div className="boot" style={{padding:"40px 16px"}}>
    <div style={{width:"100%",maxWidth:720,display:"flex",flexDirection:"column",alignItems:"center",gap:30,textAlign:"center"}}>
      <div ref={tileRef} className="pop" style={{width:88,height:88,borderRadius:26,background:"var(--accent)",display:"flex",alignItems:"center",justifyContent:"center"}}><DrawnLogo size={48} color="#fff" sw={2.2} delay={0.45} duration={1.4}/></div>
      <div className="pg2" style={{display:"flex",flexDirection:"column",gap:8}}>
        <h1 className="display" style={{margin:0,fontSize:44,fontWeight:800,letterSpacing:"-.03em",lineHeight:1.1}}>Welcome back, {first}</h1>
        <p style={{margin:0,fontSize:16,color:"var(--text2)"}}>Here's what happened while you were away.</p>
      </div>
      <div className="pg3" style={{width:"100%",display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(200px,1fr))",gap:14}}>
        <WelcomeCard label="Runs since yesterday" value={s?.total} sub={s?`${s.ok} succeeded`:" "} onClick={()=>onContinue("logs",s?{from:s.since}:null)}/>
        <WelcomeCard label="Running now" value={s?.running} color="var(--accentText)" sub="Open schedules" onClick={()=>onContinue("schedules")}/>
        <WelcomeCard label="Needs attention" value={s?.bad} color={s&&s.bad?"var(--badText)":"var(--okText)"} sub={s&&s.bad?`Schedule${s.bad===1?"":"s"} still failing`:"Nothing failing — nice"} onClick={()=>onContinue("schedules",{failing:true})}/>
      </div>
      <button type="button" className="btn btn-primary pg3" onClick={()=>onContinue("summary")} autoFocus style={{height:48,padding:"0 28px",fontSize:16,borderRadius:12}}>Continue to Conductor<Icon name="M5 12h14M12 5l7 7-7 7" size={18}/></button>
    </div>
  </div>;
}

// Welcome → app: "dive and draw". The ∞ tile grows into a blue screen, one big
// ∞ draws itself, then the blue clears to the app (about 2.7 s in all).
//   0 ms     page fades behind, tile's small ∞ fades, tile grows (0.7 s)
//   800 ms   big ∞ draws (1.1 s)
//   1850 ms  the app mounts under the blue
//   2000 ms  blue fades away (0.6 s) while the page content rises in
function DiveTransition({rect,onAppReady,onDone}){
  const [phase,setPhase]=useState(0);
  // Measure once: re-renders while the app mounts underneath must not move anything.
  const [{W,H,r}]=useState(()=>{const W=document.documentElement.clientWidth||window.innerWidth,H=document.documentElement.clientHeight||window.innerHeight;
    return {W,H,r:rect||{x:W/2-44,y:H/2-150,w:88,h:88}};});
  const cx=r.x+r.w/2,cy=r.y+r.h/2;
  // big enough to cover the farthest corner of the window
  const scale=Math.ceil(2*Math.hypot(Math.max(cx,W-cx),Math.max(cy,H-cy))/r.w)+1;
  const big=Math.round(Math.min(260,W*.4));
  useEffect(()=>{
    const root=document.documentElement;
    // The page background shows in the scrollbar gutter, which the overlay can't cover.
    // Tint it blue, then fade it back together with the overlay so its edge doesn't jump.
    const reset=()=>{root.style.backgroundColor="";root.style.transition="";};
    const t=[];const at=(ms,fn)=>t.push(setTimeout(fn,ms));
    requestAnimationFrame(()=>requestAnimationFrame(()=>setPhase(1)));
    at(450,()=>{root.style.backgroundColor="var(--accent)";});
    at(800,()=>setPhase(2));
    at(1850,()=>onAppReady());
    at(2000,()=>{setPhase(3);root.style.transition="background-color .6s ease";root.style.backgroundColor="var(--bg)";});
    at(2650,()=>{reset();onDone();});
    return()=>{t.forEach(clearTimeout);reset();};
  },[]);
  return <div aria-hidden="true" style={{position:"fixed",left:0,top:0,width:W,height:H,zIndex:9999,pointerEvents:"none",opacity:phase>=3?0:1,transition:"opacity .6s ease"}}>
    <div style={{position:"absolute",inset:0,background:"var(--bg)",opacity:phase>=1?1:0,transition:"opacity .25s ease"}}/>
    <div style={{position:"absolute",left:r.x,top:r.y,width:r.w,height:r.h,borderRadius:phase>=1?4:26,background:"var(--accent)",display:"flex",alignItems:"center",justifyContent:"center",
      transform:`scale(${phase>=1?scale:1})`,transition:"transform .7s cubic-bezier(.6,0,.4,1),border-radius .7s",willChange:"transform"}}>
      <span style={{display:"flex",opacity:phase>=1?0:1,transition:"opacity .12s"}}>
        <svg width={48} height={48} viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2.2" strokeLinecap="round"><path d="M12 12c-2-2.5-4-4-6-4a4 4 0 0 0 0 8c2 0 4-1.5 6-4z"/><path d="M12 12c2 2.5 4 4 6 4a4 4 0 0 0 0-8c-2 0-4 1.5-6 4z"/></svg>
      </span>
    </div>
    {/* Placed in pixels from the window size at the start, not centred in the
        overlay, so it can't slide when the page's scrollbar comes back. */}
    {phase>=2&&<div style={{position:"absolute",left:Math.round(W/2-big/2),top:Math.round(H/2-big/2),width:big,height:big}}><DrawnLogo size={big} color="#fff" sw={1.6} delay={0} duration={1.1}/></div>}
  </div>;
}