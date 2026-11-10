// ─── overview.jsx ────────────────────────────────────────────────────────────
// Summary and Run history pages, plus the run log drawer.

const JOB_TYPES=[["all","All"],["script","Scripts"],["tableau","Tableau"],["sharepoint","SharePoint"]];
const TYPE_COLOR={script:"var(--catScript)",tableau:"var(--catTableau)",sharepoint:"var(--catSP)"};
const runName=l=>l.script_name||l.schedule_name||"—";

function JobTypePills({value,onChange,counts}){
  return <div style={{display:"flex",gap:8,flexWrap:"wrap"}} role="group" aria-label="Job type">
    {JOB_TYPES.map(([v,l])=><button key={v} type="button" className={"pill"+(value===v?" on":"")} aria-pressed={value===v} onClick={()=>onChange(v)}>
      {v!=="all"&&<span className="dot8" style={{background:value===v?"#fff":TYPE_COLOR[v]}}/>}{l}{counts&&counts[v]!=null&&<span className="count">{counts[v]}</span>}
    </button>)}
  </div>;
}

// ─── Log drawer ───────────────────────────────────────────────────────────────
function LogDrawer({log,onClose}){
  const {stopRun}=useApp();
  const [full,setFull]=useState(log);const [loading,setLoading]=useState(true);const [err,setErr]=useState("");
  const load=()=>api.getLog(log.id).then(d=>{setFull(d);setErr("");}).catch(e=>setErr(e.message)).finally(()=>setLoading(false));
  useEffect(()=>{setFull(log);setLoading(true);load();},[log.id]);
  const isRunning=full.status==="running"||full.status==="started";
  useInterval(()=>{if(isRunning)load();},isRunning?3000:null,[isRunning]);
  const outRef=useRef(null);
  useEffect(()=>{if(isRunning&&outRef.current)outRef.current.scrollTop=outRef.current.scrollHeight;},[full.output]);
  const Recip=({to,cc})=>(to||cc)?<div className="section-box tint" style={{fontSize:13}}>
    {to&&<div style={{display:"flex",gap:10,marginBottom:cc?6:0}}><span className="muted" style={{width:28,flexShrink:0}}>To</span><span style={{wordBreak:"break-all"}}>{to}</span></div>}
    {cc&&<div style={{display:"flex",gap:10}}><span className="muted" style={{width:28,flexShrink:0}}>CC</span><span style={{wordBreak:"break-all"}}>{cc}</span></div>}
  </div>:null;
  return <Drawer title={runName(full)} sub={<span style={{display:"inline-flex",gap:8,alignItems:"center"}}><TypeTag type={full.log_type}/>Run #{full.id}</span>} onClose={onClose}
    footer={<>{isRunning&&<button className="btn btn-danger" onClick={async()=>{await stopRun(full);load();}}><Icon name="stop" size={14}/>Stop run</button>}<span style={{flex:1}}/><button className="btn btn-primary" onClick={onClose}>Close</button></>}>
    <div className="kv" style={{marginBottom:16}}>
      <div><div className="k">Status</div><div className="v"><StatusChip status={full.status}/></div></div>
      <div><div className="k">Started</div><div className="v">{fmtDate(full.started_at)}</div></div>
      <div><div className="k">Duration</div><div className="v">{isRunning?<span className="blink">Running…</span>:msStr(full.duration_ms)}</div></div>
      <div><div className="k">Trigger</div><div className="v" style={{textTransform:"capitalize"}}>{full.trigger||"—"}</div></div>
      <div><div className="k">Triggered by</div><div className="v">{full.triggered_by_name||full.triggered_by||"—"}</div></div>
      {full.sp_site_name&&<div><div className="k">SharePoint site</div><div className="v">{full.sp_site_name}{full.sp_folder?<div className="small muted mono">{full.sp_folder}</div>:null}</div></div>}
    </div>
    {full.log_type==="tableau"&&<Recip to={full.email_to} cc={full.cc_to}/>}
    {full.log_type==="script"&&full.recipients?.length>0&&<Recip to={(full.recipients||[]).join("; ")}/>}
    {full.log_type==="sharepoint"&&<Recip to={full.notify_email_to} cc={full.notify_cc_to}/>}
    <ErrNote>{err}</ErrNote>
    {full.error&&<><label className="lbl">Error</label><div className="errbox" style={{maxHeight:300,marginBottom:14}}>{full.error}</div></>}
    {full.output&&<><label className="lbl">Output{isRunning&&<span className="muted" style={{fontWeight:400}}> · updating live</span>}</label><div ref={outRef} className="console" style={{maxHeight:420}}>{full.output}</div></>}
    {!full.output&&!full.error&&(loading?<div style={{display:"flex",gap:8,alignItems:"center"}} className="muted small"><Spinner size={13}/>Loading log…</div>:<Empty title={isRunning?"Waiting for output…":"No output captured for this run"} icon="terminal"/>)}
  </Drawer>;
}

// ─── Summary ──────────────────────────────────────────────────────────────────
// Fills the spare space in "Needs attention" so it lines up with "Up next".
function AllClear({title,sub}){
  return <div className="all-clear"><span className="all-clear-ic"><Icon name="check" size={18}/></span><b>{title}</b><span>{sub}</span></div>;
}
function Summary(){
  const {user,go,runsTick}=useApp();
  const [jobType,setJobType]=useState("all");const [period,setPeriod]=useState("month");
  const [chart,setChart]=useState(()=>peek("/analytics/runs?period=month&job_type=all",null));const [stats,setStats]=useState(()=>peek("/summary/stats?job_type=all",null));const [loading,setLoading]=useState(true);
  const [fails,setFails]=useState(()=>peek("/schedules/",[]).filter(isFailing));
  const [failLogs,setFailLogs]=useState({});   // schedule id → its latest failed run (for View log)
  const [next,setNext]=useState(()=>peek("/schedules/",[]).filter(s=>s.is_active&&s.next_run_utc&&!(s.name||"").startsWith("[Ad-hoc]")).sort((a,b)=>toDate(a.next_run_utc)-toDate(b.next_run_utc)).slice(0,5));
  const [drawer,setDrawer]=useState(null);
  const gen=useRef(0);
  // `shown` = which filter the numbers on screen belong to. Animations replay
  // only when this changes, i.e. when the new data has actually arrived, so a
  // filter click never animates the previous filter's bars.
  const want=`${jobType}|${period}`;
  const [shown,setShown]=useState(want);
  const load=async(silent)=>{
    const g=++gen.current,k=want;if(!silent)setLoading(true);
    try{
      const [s,c]=await Promise.all([api.summary(jobType),api.analytics(period,jobType)]);
      if(g!==gen.current)return;setStats(s);setChart(c);setShown(k);
    }catch(e){console.error("[Summary]",e);}finally{if(g===gen.current)setLoading(false);}
  };
  useEffect(()=>{
    // Already looked at this filter? Show it instantly from the cache.
    const cs=peek(`/summary/stats?job_type=${jobType}`,null),cc=peek(`/analytics/runs?period=${period}&job_type=${jobType}`,null);
    if(cs&&cc){setStats(cs);setChart(cc);setShown(want);}
    load(!!(cs&&cc));
  },[jobType,period]);
  const pending=shown!==want;
  const fade={opacity:pending?.55:1,transition:"opacity .2s"};
  useInterval(()=>load(true),30000,[jobType,period]);
  useEffect(()=>{if(runsTick)load(true);},[runsTick]);
  useEffect(()=>{
    Promise.all([api.getSchedules(),api.getLogs({status:"failed",limit:300}).catch(()=>[])]).then(([ss,ls])=>{
      const f=ss.filter(isFailing).sort((a,b)=>toDate(b.last_run_utc)-toDate(a.last_run_utc));setFails(f);
      const m={};f.forEach(s=>{const l=ls.find(x=>x.schedule_id===s.id||((s.schedule_type||"script")==="script"&&s.script_id&&x.script_id===s.script_id));if(l)m[s.id]=l;});setFailLogs(m);
      setNext(ss.filter(s=>s.is_active&&s.next_run_utc&&!(s.name||"").startsWith("[Ad-hoc]")).sort((a,b)=>toDate(a.next_run_utc)-toDate(b.next_run_utc)).slice(0,5));}).catch(()=>{});
  },[runsTick]);
  // Numbers count up again from 0 when the page opens or a filter changes.
  const replay=shown;
  const sum=chart?.summary||{};const b=chart?.buckets||[];
  const range=b.length?{from:b[0].from,to:b[b.length-1].to}:{};
  const rate=(chart?.total||[]).map((t,i)=>t?Math.round(chart.success[i]/t*100):null).filter(v=>v!=null);
  const toLogs=extra=>go("logs",{jobType,...range,...extra});
  const cards=[
    {label:"Total runs",value:sum.total!=null?<CountUp value={sum.total} replay={replay}/>:"—",spark:chart?.total,color:"var(--accent)",go:()=>toLogs({}),title:"Open these runs in Run history"},
    {label:"Success rate",value:sum.success_rate!=null?<CountUp value={sum.success_rate} replay={replay} format={v=>(Math.round(v*10)/10)+"%"}/>:"—",spark:rate,color:"var(--ok)",go:()=>toLogs({status:"success"}),title:"Open successful runs"},
    {label:"Failed runs",value:sum.failed!=null?<CountUp value={sum.failed} replay={replay}/>:"—",spark:chart?.failed,color:"var(--bad)",go:()=>toLogs({status:"failed"}),title:"Open failed runs"},
    {label:"Avg duration",value:sum.avg_duration_ms?<CountUp value={sum.avg_duration_ms} replay={replay} format={v=>msStr(v)}/>:"—",sub:"successful runs",color:"var(--text3)",go:()=>toLogs({status:"success"}),title:"Open successful runs"},
  ];
  const byType=chart?.by_type||{};
  const segs=[["script","Scripts"],["tableau","Tableau"],["sharepoint","SharePoint"]].map(([k,l])=>({key:k,label:l,value:byType[k]||0,color:TYPE_COLOR[k]}));
  const periodLabel={day:"Today, by hour",week:"This week, by day",month:"This month, by day",year:"This year, by month"}[period];
  return <div style={{display:"flex",flexDirection:"column",gap:20}}>
    <div className="toolbar pg">
      <div><div className="display" style={{fontSize:15,fontWeight:700}}>Welcome back, {(user?.name||"").split(" ")[0]}</div><div className="small muted">{chart?.period_label||" "}</div></div>
      <span className="spacer"/>
      <JobTypePills value={jobType} onChange={setJobType}/>
      <Seg value={period} onChange={setPeriod} options={[["day","Day"],["week","Week"],["month","Month"],["year","Year"]]} ariaLabel="Period"/>
    </div>
    <div className="stats pg" style={fade} aria-busy={pending}>
      {cards.map(c=><button key={c.label} type="button" className="stat lift" onClick={c.go} title={c.title}>
        <span className="lbl2">{c.label}</span>
        <span style={{display:"flex",alignItems:"flex-end",justifyContent:"space-between",gap:10,width:"100%"}}>
          <span className="big" style={{color:loading&&!chart?"var(--border2)":"var(--text)"}}>{c.value}</span>
          {c.spark&&c.spark.length>1?<Sparkline key={replay} values={c.spark} color={c.color}/>:c.sub?<span className="small muted">{c.sub}</span>:null}
        </span>
      </button>)}
    </div>
    <div className="cols eq pg2" style={fade} aria-busy={pending}>
      <div className="card">
        <div className="card-head"><div><div className="card-title">Runs over time</div><div className="card-sub">{periodLabel} · click a bar to open those runs</div></div>
          <div className="legend"><span><i style={{background:"var(--ok)"}}/>Successful</span><span><i style={{background:"var(--bad)"}}/>Failed</span></div></div>
        <div style={{padding:"14px 16px 8px"}}>
          {chart?<MirrorBars key={shown} height={300} stagger={50} labels={chart.labels} success={chart.success} failed={chart.failed} onPick={i=>b[i]&&toLogs({from:b[i].from,to:b[i].to})}/>:<div style={{height:260,display:"flex",alignItems:"center",justifyContent:"center"}}><Spinner size={22}/></div>}
        </div>
      </div>
      <div className="card">
        <div className="card-head"><div><div className="card-title">Runs by type</div><div className="card-sub">Click a type to filter this page</div></div></div>
        <div className="card-pad" style={{flex:1,display:"flex",alignItems:"center",justifyContent:"center"}}>{chart?<Donut stacked size={160} thick={20} key={shown.split("|")[1]} replay={replay} segments={segs} active={jobType==="all"?null:jobType} onPick={k=>setJobType(jobType===k?"all":k)}/>:<Skel h={150}/>}</div>
      </div>
    </div>
    <div className="cols-even stretch pg3">
      <div className="card col-card">
        <div className="card-head"><div><div className="card-title">Needs attention</div><div className="card-sub">Schedules whose last run failed</div></div>{fails.length>5&&<button className="link-btn" style={{fontSize:13}} onClick={()=>go("schedules",{failing:true})}>All failing ({fails.length})</button>}</div>
        {fails.length===0?<AllClear title="Nothing failing. Nice." sub="Every schedule’s last run succeeded"/>
          :fails.slice(0,5).map(s=>{const l=failLogs[s.id];const err=(l&&l.error)||s.last_error||"Failed";const open=()=>l?setDrawer(l):go("schedules",{openId:s.id});
            return <div key={s.id} className="list-row click" onClick={open}>
            <span className="dot8" style={{background:"var(--bad)"}}/>
            <div style={{flex:1,minWidth:0}}><div className="trunc" style={{fontWeight:600}}>{s.name||s.script_name||s.dashboard_name}</div><div className="small muted trunc" title={err}>{fmtWhen(s.last_run_utc)} · {err.split("\n").filter(Boolean).slice(-1)[0]}</div></div>
            <button className="btn btn-sm" onClick={e=>{e.stopPropagation();open();}}>{l?"View log":"Open"}</button>
          </div>;})}
        {fails.length>0&&fails.length<5&&<AllClear title="All other schedules are healthy" sub="Their last runs succeeded"/>}
      </div>
      <div className="card col-card">
        <div className="card-head"><div><div className="card-title">Up next</div><div className="card-sub">Next 5 scheduled runs</div></div><button className="link-btn" style={{fontSize:13}} onClick={()=>go("schedules")}>All schedules</button></div>
        {next.length===0?<div className="list-row muted small">Nothing scheduled.</div>
          :next.map(s=><div key={s.id} className="list-row click" onClick={()=>go("schedules",{openId:s.id})}>
            <span className="dot8" style={{background:TYPE_COLOR[s.schedule_type||"script"]}}/>
            <div style={{flex:1,minWidth:0}}><div className="trunc" style={{fontWeight:600}}>{s.name||s.script_name||s.dashboard_name}</div><div className="small muted">{TYPE_LABEL[s.schedule_type||"script"]}</div></div>
            <span className="small" style={{fontWeight:600,whiteSpace:"nowrap"}}>{fmtWhen(s.next_run_utc)}</span>
          </div>)}
      </div>
    </div>
    <div className="card pg3">
      <div className="card-head"><div className="card-title">Recent activity</div><button className="link-btn" style={{fontSize:13}} onClick={()=>go("logs")}>View all run history</button></div>
      <div className="tbl-wrap"><table className="tbl">
        <thead><tr><th>Name</th><th>Type</th><th>Triggered by</th><th>Started</th><th>Duration</th><th>Status</th></tr></thead>
        {!stats?<SkelRows rows={5} cols={6}/>:<tbody>
          {(stats.recent_logs||[]).length===0&&<tr><td colSpan={6}><Empty title="No runs yet" sub="Run a script to see activity here"/></td></tr>}
          {(stats.recent_logs||[]).map(l=><tr key={l.id} className="row" onClick={()=>setDrawer(l)} tabIndex={0} onKeyDown={e=>e.key==="Enter"&&setDrawer(l)}>
            <td className="name">{runName(l)}</td><td><TypeTag type={l.log_type}/></td><td>{l.triggered_by_name||"—"}</td>
            <td>{fmtWhen(l.started_at)}</td><td>{msStr(l.duration_ms)}</td><td><StatusChip status={l.status}/></td>
          </tr>)}
        </tbody>}
      </table></div>
    </div>
    {drawer&&<LogDrawer log={drawer} onClose={()=>setDrawer(null)}/>}
  </div>;
}

// ─── Run history ──────────────────────────────────────────────────────────────
// Every filter (type, status, name, dates, heatmap cell) runs on the server and
// the table asks for one page at a time, so counts are exact and every page is
// as quick as the first. The heatmap shows when runs happen (Pacific time).
const STATUS_WORD={all:"",success:"successful ",failed:"failed ",running:"running ",stopped:"stopped "};
const HEAT_COLOR={all:"var(--accent)",success:"var(--ok)",failed:"var(--bad)",running:"var(--accent)",stopped:"var(--warn)"};
const PAGE_SIZES=[25,50,100];
// Page numbers: first, last, and the ones around the current page (5 near either end)
function pageList(page,pages){
  if(pages<=7)return Array.from({length:pages},(_,i)=>i+1);
  let a=Math.max(2,page-1),b=Math.min(pages-1,page+1);
  if(page<=4){a=2;b=5;}if(page>=pages-3){a=pages-4;b=pages-1;}
  const out=[1];if(a>2)out.push("…a");for(let i=a;i<=b;i++)out.push(i);if(b<pages-1)out.push("…b");out.push(pages);return out;
}
function RunPager({page,pages,total,size,onPage,onSize,word}){
  const n=v=>Number(v).toLocaleString();
  const from=total?(page-1)*size+1:0,to=Math.min(total,page*size);
  return <div className="pagebar">
    <span className="pb-range"><b>{n(from)}–{n(to)}</b> of {n(total)} {word}run{total===1?"":"s"}</span>
    {pages>1&&<div className="pb-pages">
      <button className="btn btn-sm" disabled={page<=1} onClick={()=>onPage(page-1)}><Icon name="chevL" size={14}/>Prev</button>
      {pageList(page,pages).map(p=>typeof p==="string"?<span key={p} className="muted">…</span>
        :<button key={p} className={"btn btn-sm"+(p===page?" btn-primary":"")} aria-current={p===page?"page":undefined} onClick={()=>onPage(p)}>{p}</button>)}
      <button className="btn btn-sm" disabled={page>=pages} onClick={()=>onPage(page+1)}>Next<Icon name="chevR" size={14}/></button>
    </div>}
    <span className="pb-size">Rows per page<select className="field" value={size} onChange={e=>onSize(+e.target.value)} aria-label="Rows per page">{PAGE_SIZES.map(v=><option key={v} value={v}>{v}</option>)}</select></span>
  </div>;
}
function RunHistory({params}){
  const {stopRun,runsTick}=useApp();
  const p=params||{};
  const [status,setStatus]=useState(p.status||"all");const [jobType,setJobType]=useState(p.jobType||"all");
  const [dateFrom,setDateFrom]=useState(p.from||"");const [dateTo,setDateTo]=useState(p.to||"");
  const [search,setSearch]=useState("");const sq=useDebounced(search.trim(),300);
  const [group,setGroup]=useState("none");
  const [size,setSizeRaw]=useState(()=>{const v=+lsGet("rh_page_size",50);return PAGE_SIZES.includes(v)?v:50;});
  const [page,setPage]=useState(1);
  const [slot,setSlot]=useState(null);           // picked heatmap cell {wd,hr}
  const plain=!(p.from||p.to||p.status||p.jobType);
  const [logs,setLogs]=useState(()=>plain?peek(`/logs/?limit=${size}&offset=0`,[]):[]);const [loading,setLoading]=useState(true);
  const [counts,setCounts]=useState(()=>plain?peek("/logs/counts?",null):null);
  const [heat,setHeat]=useState(()=>plain?peek("/logs/heatmap?",null):null);
  // Which filters the heatmap's numbers belong to. Its animation plays once per set of
  // filters: cached numbers count as loaded, and a refresh with the same filters doesn't replay it.
  const [heatFor,setHeatFor]=useState(()=>heat?"all|all|||":null);
  const [sel,setSel]=useState(p.logId?{id:p.logId}:null);
  const tableRef=useRef(null);
  useEffect(()=>{const q=params||{};setStatus(q.status||"all");setJobType(q.jobType||"all");setDateFrom(q.from||"");setDateTo(q.to||"");setSlot(null);if(q.logId)setSel({id:q.logId});},[params]);
  // Keep the table's header row just under the sticky top bar
  useEffect(()=>{const tb=document.querySelector(".topbar");if(!tb)return;const root=document.documentElement;
    const set=()=>root.style.setProperty("--topH",tb.offsetHeight+"px");set();
    const ro=new ResizeObserver(set);ro.observe(tb);return()=>{ro.disconnect();root.style.removeProperty("--topH");};},[]);
  const filt=()=>{const q={};if(jobType!=="all")q.log_type=jobType;if(sq)q.q=sq;if(dateFrom)q.date_from=dateFrom;if(dateTo)q.date_to=dateTo;return q;};
  const fkey=`${jobType}|${status}|${sq}|${dateFrom}|${dateTo}`;
  const gen=useRef(0),hgen=useRef(0);
  const load=async(silent,pg=page,sz=size,sl=slot)=>{const g=++gen.current;if(!silent)setLoading(true);
    try{const f=filt();const sf=sl?{wd:sl.wd,hr:sl.hr}:{};
      const q={...f};if(status!=="all")q.status=status;Object.assign(q,sf,{limit:sz,offset:(pg-1)*sz});
      const [ls,c]=await Promise.all([api.getLogs(q),api.logCounts({...f,...sf}).catch(()=>null)]);
      if(g!==gen.current)return;setLogs(ls);if(c)setCounts(c);}
    catch(e){console.error(e);}finally{if(g===gen.current)setLoading(false);}};
  // The heatmap replays its animation when numbers for new filters arrive (not on refresh)
  const loadHeat=()=>{const h=++hgen.current;const k=fkey;const q=filt();if(status!=="all")q.status=status;
    api.logHeatmap(q).then(d=>{if(h!==hgen.current)return;setHeat(d);setHeatFor(k);}).catch(()=>{});};
  // Any filter change goes back to page 1
  useEffect(()=>{setPage(1);load(false,1);loadHeat();},[status,jobType,sq,dateFrom,dateTo]);
  const pickSlot=(wd,hr)=>{const next=slot&&slot.wd===wd&&slot.hr===hr?null:{wd,hr};setSlot(next);setPage(1);load(false,1,size,next);};
  const clearSlot=()=>{if(slot){setSlot(null);setPage(1);load(false,1,size,null);}};
  const goPage=pg=>{setPage(pg);load(false,pg);
    const el=tableRef.current;if(el){const top=el.getBoundingClientRect().top;const th=parseInt(getComputedStyle(document.documentElement).getPropertyValue("--topH"))||0;if(top<th)window.scrollBy({top:top-th-12,behavior:"smooth"});}};
  const setSize=v=>{setSizeRaw(v);lsSet("rh_page_size",String(v));setPage(1);load(false,1,v);};
  const anyRunning=logs.some(l=>l.status==="running"||l.status==="started");
  // Refresh the page you're on every 8s while something on it is running, otherwise every 30s,
  // and right away when the header sees a run finish.
  useInterval(()=>{if(!document.hidden){load(true);loadHeat();}},anyRunning?8000:30000,[anyRunning,fkey,page,size,slot]);
  useEffect(()=>{if(runsTick){load(true);loadHeat();}},[runsTick]);
  const grouped=useMemo(()=>{
    if(group==="none")return null;const map={};
    logs.forEach(l=>{const d=toDate(l.started_at);let key;
      if(group==="day")key=d.toLocaleDateString("en-US",{weekday:"short",month:"short",day:"numeric",year:"numeric",timeZone:TZ});
      else if(group==="month")key=d.toLocaleDateString("en-US",{month:"long",year:"numeric",timeZone:TZ});
      else key=new Intl.DateTimeFormat("en-US",{year:"numeric",timeZone:TZ}).format(d);
      if(!map[key])map[key]={key,logs:[],success:0,failed:0};map[key].logs.push(l);if(l.status==="success")map[key].success++;if(l.status==="failed")map[key].failed++;});
    return Object.values(map).sort((a,b)=>toDate(b.logs[0].started_at)-toDate(a.logs[0].started_at));
  },[logs,group]);
  const total=counts?counts[status]??counts.all:null;
  const pages=total?Math.max(1,Math.ceil(total/size)):1;
  // If runs disappear (e.g. deleted) and this page no longer exists, step back
  useEffect(()=>{if(total!=null&&page>pages)goPage(pages);},[total,pages]);
  const dated=!!(dateFrom||dateTo);
  const word=STATUS_WORD[status]||"";
  const heatPending=heatFor!==fkey;
  const clearAll=()=>{setDateFrom("");setDateTo("");setStatus("all");setJobType("all");setSearch("");setSlot(null);};
  const shortDay=d=>new Date(d+"T12:00:00").toLocaleDateString("en-US",{month:"short",day:"numeric"});
  const dateLabel=dateFrom&&dateTo?(dateFrom===dateTo?shortDay(dateFrom):`${shortDay(dateFrom)} – ${shortDay(dateTo)}`):dateFrom?`from ${shortDay(dateFrom)}`:dateTo?`until ${shortDay(dateTo)}`:"";
  const slotLabel=slot?`${HEAT_DAYS_LONG[slot.wd]} · ${hourRange(slot.hr)}`:"";
  // Esc clears the picked cell (unless a run's log panel is open — Esc closes that first)
  useEffect(()=>{
    const h=e=>{if(e.key==="Escape"&&!sel&&slot&&!document.querySelector(".overlay,.palette"))clearSlot();};
    document.addEventListener("keydown",h);return()=>document.removeEventListener("keydown",h);
  },[sel,slot]);
  const Table=({rows})=><div className="tbl-wrap sticky-head"><table className="tbl">
    <thead><tr><th>Name</th><th>Type</th><th>Triggered by</th><th>Started</th><th>Duration</th><th>Status</th><th className="actions"><span className="sr">Actions</span></th></tr></thead>
    {loading&&!logs.length?<SkelRows rows={8} cols={7}/>:<tbody style={{opacity:loading?.55:1,transition:"opacity .15s"}}>{rows.map(l=>{const run=l.status==="running"||l.status==="started";
      return <tr key={l.id} className={"row"+(sel&&sel.id===l.id?" sel":"")} onClick={()=>setSel(l)} tabIndex={0} onKeyDown={e=>e.key==="Enter"&&setSel(l)}>
        <td className="name">{runName(l)}</td><td><TypeTag type={l.log_type}/></td><td>{l.triggered_by_name||<span className="muted">{l.trigger==="schedule"?"Scheduler":"—"}</span>}</td>
        <td>{fmtDate(l.started_at)}</td><td>{run?<span className="blink">running</span>:msStr(l.duration_ms)}</td><td><StatusChip status={l.status}/></td>
        <td className="actions">{run?<button className="btn btn-danger btn-sm" onClick={async e=>{e.stopPropagation();if(await stopRun(l))setLogs(prev=>prev.map(r=>r.id===l.id?{...r,status:"stopped"}:r));}}>Stop</button>:<Icon name="chevR" size={15} style={{color:"var(--text3)"}}/>}</td>
      </tr>;})}</tbody>}
  </table></div>;
  const n=v=>v==null?"":Number(v).toLocaleString();
  const emptyTitle=status==="running"&&!slot?"Nothing running right now":"No runs match these filters";
  const emptySub=status==="running"&&!slot?"Running jobs show up here as soon as they start.":"Try a different type, status, name, date or hour.";
  const hc=HEAT_COLOR[status]||"var(--accent)";
  const rangeText=dated?dateLabel:"Last 4 weeks";
  return <div style={{display:"flex",flexDirection:"column",gap:20}}>
    <div className="card pg">
      <div className="card-head"><div><div className="card-title" style={{display:"flex",alignItems:"center",gap:10,flexWrap:"wrap"}}>When runs happen
          {slot&&<span className="chip chip-run" style={{padding:"2px 4px 2px 10px",fontWeight:600}}>Showing {slotLabel}<button type="button" onClick={clearSlot} aria-label="Show all hours" title="Show all hours" style={{border:"none",background:"none",color:"inherit",cursor:"pointer",display:"flex",padding:2}}><Icon name="x" size={13}/></button></span>}
        </div><div className="card-sub">{rangeText} by weekday and hour (Pacific) · {slot?"click the cell again, the ✕, or press Esc to show all hours":"click a cell to show only those runs"}</div></div>
        <div style={{display:"flex",alignItems:"center",gap:16,flexWrap:"wrap"}}>
          <span className="heat-legend">Fewer{["22%","45%","70%","100%"].map(x=><i key={x} style={{background:`color-mix(in srgb,${hc} ${x},var(--surface2))`}}/>)}More {word||""}runs</span>
          {status==="all"&&<span className="heat-legend"><span className="heat-bad" style={{position:"static",width:16,height:16,fontSize:9,boxShadow:"none"}}>n</span>Failed</span>}
        </div></div>
      <div style={{padding:"14px 18px 12px",opacity:heatPending&&heat?.55:1,transition:"opacity .2s"}}>
        {heat?<Heatmap grid={heat.grid} color={hc} badges={status==="all"} word={`${word}runs`} selected={slot} onPick={pickSlot} replay={heatFor}/>:<div style={{height:262,display:"flex",alignItems:"center",justifyContent:"center"}}><Spinner size={22}/></div>}
      </div>
    </div>
    <div className="toolbar pg2">
      <JobTypePills value={jobType} onChange={setJobType}/>
      <span className="spacer"/>
      <Seg value={status} onChange={setStatus} ariaLabel="Status" options={[["all","All runs"],["success","Success"],["failed","Failed"],["running","Running"],["stopped","Stopped"]].map(([v,l])=>[v,l,<span key="c" className="small muted" style={{marginLeft:6,fontVariantNumeric:"tabular-nums"}}>{counts?n(counts[v]):""}</span>])}/>
    </div>
    <div className="toolbar pg2" style={{marginTop:-8}}>
      <SearchBox value={search} onChange={setSearch} placeholder="Search by name…" style={{flex:"1 1 200px",maxWidth:320}}/>
      <span className="spacer"/>
      <input className="field" type="date" style={{width:"auto"}} value={dateFrom} onChange={e=>setDateFrom(e.target.value)} aria-label="From date"/>
      <span className="muted small">to</span>
      <input className="field" type="date" style={{width:"auto"}} value={dateTo} onChange={e=>setDateTo(e.target.value)} aria-label="To date"/>
      <button className="btn btn-quiet" onClick={clearAll} disabled={!dateFrom&&!dateTo&&status==="all"&&jobType==="all"&&!search&&!slot}>Clear</button>
    </div>
    <div className="card pg3" ref={tableRef}>
      <div className="card-head">
        <div className="card-sub">{loading&&!logs.length?"Loading…":total!=null?`${n(total)} ${word}run${total===1?"":"s"}`:`${logs.length} runs`}{slot?` · ${slotLabel}`:""}{dated?` · ${dateLabel}`:""}</div>
        <div style={{display:"flex",alignItems:"center",gap:8}}><span className="small muted">Group by</span><Seg value={group} onChange={setGroup} options={[["none","None"],["day","Day"],["month","Month"],["year","Year"]]}/></div>
      </div>
      {!loading&&logs.length===0?<Empty title={emptyTitle} sub={emptySub} icon="history" action={(status!=="all"||jobType!=="all"||search||dated||slot)&&<button className="btn btn-sm" onClick={clearAll}>Clear filters</button>}/>
        :grouped?<div>{grouped.map(g=><div key={g.key}>
          <div style={{display:"flex",alignItems:"center",gap:10,padding:"14px 18px 8px",borderTop:"1px solid var(--border)"}}>
            <b>{g.key}</b><span className="small muted">{g.logs.length} run{g.logs.length!==1?"s":""} on this page</span>
            {g.success>0&&<span className="chip chip-ok">{g.success} passed</span>}{g.failed>0&&<span className="chip chip-bad">{g.failed} failed</span>}
          </div><Table rows={g.logs}/></div>)}</div>
        :<Table rows={logs}/>}
      {total>0&&<RunPager page={page} pages={pages} total={total} size={size} onPage={goPage} onSize={setSize} word={word}/>}
    </div>
    {sel&&<LogDrawer log={sel} onClose={()=>setSel(null)}/>}
  </div>;
}