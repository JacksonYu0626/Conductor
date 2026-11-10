// ─── charts.jsx ──────────────────────────────────────────────────────────────
// Small SVG charts (no chart library): stacked run bars, donut, sparkline.

function useWidth(ref,fallback=600){
  const [w,setW]=useState(fallback);
  useEffect(()=>{
    if(!ref.current)return;
    const ro=new ResizeObserver(es=>{for(const e of es){const cw=Math.floor(e.contentRect.width);if(cw>0)setW(cw);}});
    ro.observe(ref.current);return()=>ro.disconnect();
  },[]);
  return w;
}
function niceMax(v){if(v<=4)return 4;const p=Math.pow(10,Math.floor(Math.log10(v)));const n=v/p;const m=n<=1?1:n<=2?2:n<=2.5?2.5:n<=5?5:10;return m*p;}

// Successful (bottom) + failed (top) per bucket. Hover = tooltip, click = onPick(index).
function RunBars({labels=[],success=[],failed=[],height=260,onPick,selected,pickHint="Click a bar to see those runs",stagger=50}){
  const anim=true;
  const wrap=useRef(null);const W=useWidth(wrap);
  const [hover,setHover]=useState(null);
  const n=labels.length;
  const padL=34,padR=8,padT=12,padB=26;
  const iw=Math.max(10,W-padL-padR),ih=height-padT-padB;
  const totals=labels.map((_,i)=>(success[i]||0)+(failed[i]||0));
  const top=Math.max(1,...totals);
  const step0=top/4;const pw=Math.pow(10,Math.floor(Math.log10(step0||1)));
  const tstep=Math.max(1,[1,2,5,10].map(m=>m*pw).find(v=>v>=step0)||1);
  const max=Math.ceil(top/tstep)*tstep;
  const step=n?iw/n:iw;const bw=Math.max(3,Math.min(34,step*.62));
  const y=v=>padT+ih-(v/max)*ih;
  const ticks=[];for(let v=0;v<=max+1e-9;v+=tstep)ticks.push(v);
  // Show as many labels as fit without overlapping (11px text ≈ 6.4px a character).
  const labW=Math.max(0,...labels.map(l=>String(l).length))*6.4+8;
  const every=Math.max(1,Math.ceil(labW/Math.max(1,step)));
  const barPath=(x,top,bottom,r)=>{const h=bottom-top;if(h<=0)return"";const rr=Math.min(r,h,bw/2);return`M${x},${bottom}V${top+rr}Q${x},${top} ${x+rr},${top}H${x+bw-rr}Q${x+bw},${top} ${x+bw},${top+rr}V${bottom}Z`;};
  const hv=hover!=null?hover:null;
  return <div ref={wrap} style={{position:"relative",width:"100%"}}>
    <svg className="chart-svg" width={W} height={height} role="img" aria-label="Runs per period, successful and failed">
      {ticks.map((t,i)=><g key={i}><line className="grid" x1={padL} x2={W-padR} y1={y(t)} y2={y(t)} strokeDasharray={i===0?"":"3 4"}/><text x={padL-8} y={y(t)+4} textAnchor="end">{Math.round(t)}</text></g>)}
      {labels.map((l,i)=>{
        const x=padL+i*step+(step-bw)/2;const s=success[i]||0,f=failed[i]||0;
        const sTop=y(s),fTop=y(s+f);const dim=(selected!=null&&selected!==i)||(hv!=null&&hv!==i);
        return <g key={i} style={{opacity:dim?.45:1,transition:"opacity .15s"}}>
          {s>0&&<path className={anim?"bar":undefined} style={{animationDelay:`${i*stagger}ms`}} d={barPath(x,sTop,y(0),f>0?0:4)} fill="var(--ok)"/>}
          {f>0&&<path className={anim?"bar":undefined} style={{animationDelay:`${i*stagger}ms`}} d={barPath(x,fTop,sTop-(s>0?2:0),4)} fill="var(--bad)"/>}
          {i%every===0&&<text x={padL+i*step+step/2} y={height-8} textAnchor="middle">{l}</text>}
          <rect className="hit" x={padL+i*step} y={padT} width={step} height={ih} fill="transparent"
            tabIndex={onPick?0:-1} role={onPick?"button":undefined} aria-label={`${l}: ${s} successful, ${f} failed`}
            onMouseEnter={()=>setHover(i)} onMouseLeave={()=>setHover(null)} onFocus={()=>setHover(i)} onBlur={()=>setHover(null)}
            onClick={()=>onPick&&onPick(i)} onKeyDown={e=>{if((e.key==="Enter"||e.key===" ")&&onPick){e.preventDefault();onPick(i);}}}/>
        </g>;
      })}
    </svg>
    {hv!=null&&(()=>{
      const cx=padL+hv*step+step/2;const left=Math.min(Math.max(cx-80,0),W-180);
      const s=success[hv]||0,f=failed[hv]||0,t=s+f;
      return <div className="tip" style={{left,top:Math.max(0,y(t)-96)}}>
        <div style={{fontWeight:700,marginBottom:2}}>{labels[hv]}</div>
        <div style={{display:"flex",alignItems:"center",gap:6}}><i style={{width:8,height:8,borderRadius:2,background:"var(--ok)",display:"inline-block"}}/>Successful <b style={{marginLeft:"auto",paddingLeft:12}}>{s}</b></div>
        <div style={{display:"flex",alignItems:"center",gap:6}}><i style={{width:8,height:8,borderRadius:2,background:"var(--bad)",display:"inline-block"}}/>Failed <b style={{marginLeft:"auto",paddingLeft:12}}>{f}</b></div>
        <div style={{opacity:.75,marginTop:2}}>{t} total{t?` · ${Math.round(s/t*100)}% success`:""}</div>
        {onPick&&t>0&&<div style={{opacity:.75}}>{pickHint}</div>}
      </div>;
    })()}
  </div>;
}

// Donut: segments [{key,label,value,color}]. Hover shows detail, click toggles a filter.
function Donut({segments=[],size=150,thick=18,active,onPick,centerLabel="runs",replay,stacked=false}){
  const anim=true;
  const [hover,setHover]=useState(null);
  const total=segments.reduce((a,s)=>a+(s.value||0),0);
  const grow=4;const r=(size-thick-grow)/2-1,c=2*Math.PI*r;
  let acc=0;
  const focus=hover||active;
  const fs=segments.find(s=>s.key===focus);
  return <div style={stacked?{display:"flex",flexDirection:"column",alignItems:"center",gap:14,width:"100%"}:{display:"flex",alignItems:"center",gap:22,flexWrap:"wrap"}}>
    <div style={{position:"relative",width:size,height:size,flexShrink:0}}>
      <svg width={size} height={size} className={anim?"donut":undefined} role="img" aria-label={`Runs by type, ${total} total`}>
        <circle cx={size/2} cy={size/2} r={r} fill="none" stroke="var(--surface2)" strokeWidth={thick}/>
        {total>0&&segments.map(s=>{
          const frac=(s.value||0)/total;const len=Math.max(0,frac*c-(segments.filter(x=>x.value>0).length>1?3:0));
          const off=-acc*c;acc+=frac;
          if(!s.value)return null;
          const dim=focus&&focus!==s.key;
          return <circle key={s.key} cx={size/2} cy={size/2} r={r} fill="none" stroke={s.color} strokeWidth={focus===s.key?thick+grow:thick}
            strokeDasharray={`${len} ${c-len}`} strokeDashoffset={off} transform={`rotate(-90 ${size/2} ${size/2})`}
            style={{cursor:onPick?"pointer":"default",opacity:dim?.35:1,transition:"opacity .15s,stroke-width .15s"}}
            onMouseEnter={()=>setHover(s.key)} onMouseLeave={()=>setHover(null)} onClick={()=>onPick&&onPick(s.key)}/>;
        })}
      </svg>
      <div style={{position:"absolute",inset:0,display:"flex",flexDirection:"column",alignItems:"center",justifyContent:"center",pointerEvents:"none"}}>
        <span className="display" style={{fontSize:26,fontWeight:800,lineHeight:1}}><CountUp value={fs?fs.value:total} replay={replay}/></span>
        <span className="small muted">{fs?`${fs.label} · ${total?Math.round(fs.value/total*100):0}%`:centerLabel}</span>
      </div>
    </div>
    <div style={stacked?{display:"flex",flexDirection:"column",gap:4,width:"100%"}:{display:"flex",flexDirection:"column",gap:4,flex:"1 1 140px",minWidth:140}}>
      {segments.map(s=>{const on=active===s.key;return <button key={s.key} type="button" onClick={()=>onPick&&onPick(s.key)} onMouseEnter={()=>setHover(s.key)} onMouseLeave={()=>setHover(null)}
        aria-pressed={on} style={{display:"flex",alignItems:"center",gap:8,padding:"7px 10px",borderRadius:10,border:"1px solid "+(on?"var(--accent)":"transparent"),background:on||hover===s.key?"var(--surface2)":"transparent",cursor:onPick?"pointer":"default",textAlign:"left",color:"var(--text)"}}>
        <span className="dot8" style={{background:s.color}}/>
        <span style={{flex:1,fontSize:13}}>{s.label}</span>
        <b style={{fontSize:13,fontVariantNumeric:"tabular-nums"}}><CountUp value={s.value} replay={replay}/></b>
        <span className="small muted" style={{width:38,textAlign:"right"}}>{total?Math.round(s.value/total*100):0}%</span>
      </button>;})}
    </div>
  </div>;
}

function Sparkline({values=[],color="var(--accent)",w=96,h=30}){
  const anim=true;
  if(!values.length)return <svg width={w} height={h}/>;
  const max=Math.max(...values,1),min=Math.min(...values,0);
  const pts=values.map((v,i)=>[values.length===1?w/2:i*(w-4)/(values.length-1)+2,h-3-((v-min)/(max-min||1))*(h-6)]);
  const d=pts.map((p,i)=>(i?"L":"M")+p[0].toFixed(1)+","+p[1].toFixed(1)).join("");
  return <svg width={w} height={h} aria-hidden="true">
    <path d={d+`L${pts[pts.length-1][0]},${h}L${pts[0][0]},${h}Z`} fill={color} opacity=".1"/>
    <path className={anim?"draw":undefined} pathLength="1" d={d} fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>;
}

// Tiny per-day bars used on Profile.
function MiniBars({values=[],labels=[],height=90,color="var(--accent)",stagger=60}){
  const anim=true;
  const wrap=useRef(null);const W=useWidth(wrap,300);
  const [hover,setHover]=useState(null);
  const max=Math.max(1,...values);const n=values.length||1;const step=W/n;const bw=Math.min(28,step*.6);
  return <div ref={wrap} style={{position:"relative"}}>
    <svg width={W} height={height+18} className="chart-svg">
      {values.map((v,i)=>{const bh=(v/max)*(height-6);const x=i*step+(step-bw)/2;return <g key={i} onMouseEnter={()=>setHover(i)} onMouseLeave={()=>setHover(null)}>
        <rect className={anim?"bar":undefined} style={{animationDelay:`${i*stagger}ms`}} x={x} y={height-bh} width={bw} height={Math.max(bh,v?2:0)} rx="4" fill={color} opacity={hover==null||hover===i?1:.45}/>
        <rect x={i*step} y={0} width={step} height={height} fill="transparent"/>
        <text x={i*step+step/2} y={height+14} textAnchor="middle">{labels[i]}</text>
      </g>;})}
    </svg>
    {hover!=null&&<div className="tip" style={{left:Math.min(Math.max(hover*step,0),W-150),top:0}}>{labels[hover]} · <b>{values[hover]}</b> run{values[hover]===1?"":"s"}</div>}
  </div>;
}

// Weekday × hour heatmap for Run history. grid[wd][hr] = {n, failed}, wd 0 = Monday,
// hours in Pacific time. Shade = how many runs (n); red badge = failed runs
// (only when every status is counted). Click a cell = onPick(wd,hr), again to clear.
const HEAT_DAYS_LONG=["Mondays","Tuesdays","Wednesdays","Thursdays","Fridays","Saturdays","Sundays"];
const HEAT_DAYS_SHORT=["Mon","Tue","Wed","Thu","Fri","Sat","Sun"];
const hourLabel=h=>`${(h%12)||12} ${h<12?"AM":"PM"}`;
const hourRange=h=>`${(h%12)||12}–${((h+1)%12)||12} ${h+1<12||h+1===24?"AM":"PM"}`;
function Heatmap({grid,color="var(--accent)",badges=true,word="runs",selected,onPick,replay}){
  const wrap=useRef(null);const W=useWidth(wrap,900);
  const [hover,setHover]=useState(null);
  const g=grid||Array.from({length:7},()=>Array.from({length:24},()=>({n:0,failed:0})));
  const max=Math.max(0,...g.flat().map(c=>c.n));
  const level=n=>!n||!max?0:Math.max(1,Math.ceil(n/max*4));
  const shade=["0%","22%","45%","70%","100%"];
  const every=W<520?6:W<820?3:2;
  const hv=hover;const sel=selected;
  const cellW=(W-44)/24;
  return <div ref={wrap} className="heat" style={{position:"relative"}}>
    <div className="heat-grid" key={replay}>
      {g.map((row,wd)=><React.Fragment key={wd}>
        <div className="heat-day">{HEAT_DAYS_SHORT[wd]}</div>
        {row.map((c,hr)=>{const on=sel&&sel.wd===wd&&sel.hr===hr;const dim=sel&&!on;
          return <button type="button" key={hr} className={"heat-cell"+(on?" on":"")}
            style={{"--c":color,"--p":shade[level(c.n)],opacity:dim?.4:1,animationDelay:`${hr*14+wd*10}ms`}}
            aria-label={`${HEAT_DAYS_LONG[wd]} ${hourRange(hr)}: ${c.n} ${word}${badges&&c.failed?`, ${c.failed} failed`:""}`}
            onMouseEnter={()=>setHover({wd,hr})} onMouseLeave={()=>setHover(null)} onFocus={()=>setHover({wd,hr})} onBlur={()=>setHover(null)}
            onClick={()=>onPick&&(c.n>0||on)&&onPick(wd,hr)} disabled={!c.n&&!on}>
            {badges&&c.failed>0&&<span className="heat-bad">{c.failed>99?"99+":c.failed}</span>}
          </button>;})}
      </React.Fragment>)}
      <div/>
      {Array.from({length:24},(_,h)=><div key={h} className="heat-hour">{h%every===0?hourLabel(h):""}</div>)}
    </div>
    {hv&&(()=>{const c=g[hv.wd][hv.hr];const cx=44+hv.hr*cellW+cellW/2;const left=Math.min(Math.max(cx-95,0),W-200);
      const on=sel&&sel.wd===hv.wd&&sel.hr===hv.hr;
      return <div className="tip" style={{left,top:hv.wd*34+40}}>
        <div style={{fontWeight:700}}>{HEAT_DAYS_LONG[hv.wd]}, {hourRange(hv.hr)}</div>
        <div>{c.n.toLocaleString()} {c.n===1?word.replace(/s$/,""):word}{badges?` · ${c.failed} failed`:""}</div>
        {c.n>0&&onPick&&<div style={{opacity:.75}}>{on?"Click to show all hours":"Click to show only these runs"}</div>}
      </div>;})()}
  </div>;
}

// Mirrored bars for Summary: successful runs grow up from a centre line, failed
// runs grow down below it (own scale), so even one failure is easy to see.
// Hover = tooltip, click = onPick(index).
function niceStep(top,ticks){const s0=top/ticks;const pw=Math.pow(10,Math.floor(Math.log10(s0||1)));return Math.max(1,[1,2,5,10].map(m=>m*pw).find(v=>v>=s0)||1);}
function MirrorBars({labels=[],success=[],failed=[],height=300,onPick,selected,pickHint="Click a bar to see those runs",stagger=50}){
  const wrap=useRef(null);const W=useWidth(wrap);
  const [hover,setHover]=useState(null);
  const n=labels.length;
  const padL=34,padR=8,padT=12,padB=26;
  const iw=Math.max(10,W-padL-padR),ih=height-padT-padB;
  const anyFail=failed.some(v=>v>0);
  const upH=Math.round(ih*(anyFail?.68:.86)),dnH=ih-upH;      // space above / below the centre line
  const mid=padT+upH;
  const upStep=niceStep(Math.max(1,...success),3),upMax=Math.max(upStep,Math.ceil(Math.max(1,...success)/upStep)*upStep);
  const dnStep=niceStep(Math.max(1,...failed),2),dnMax=Math.max(dnStep,Math.ceil(Math.max(1,...failed)/dnStep)*dnStep);
  const yUp=v=>mid-(v/upMax)*(upH-2),yDn=v=>mid+(v/dnMax)*(dnH-4);
  const upTicks=[];for(let v=upStep;v<=upMax+1e-9;v+=upStep)upTicks.push(v);
  const dnTicks=[];if(anyFail)for(let v=dnStep;v<=dnMax+1e-9;v+=dnStep)dnTicks.push(v);
  const step=n?iw/n:iw;const bw=Math.max(3,Math.min(34,step*.62));
  const labW=Math.max(0,...labels.map(l=>String(l).length))*6.4+8;
  const every=Math.max(1,Math.ceil(labW/Math.max(1,step)));
  const up=(x,top,bottom)=>{const h=bottom-top;if(h<=0)return"";const r=Math.min(4,h,bw/2);return`M${x},${bottom}V${top+r}Q${x},${top} ${x+r},${top}H${x+bw-r}Q${x+bw},${top} ${x+bw},${top+r}V${bottom}Z`;};
  const dn=(x,top,bottom)=>{const h=bottom-top;if(h<=0)return"";const r=Math.min(4,h,bw/2);return`M${x},${top}V${bottom-r}Q${x},${bottom} ${x+r},${bottom}H${x+bw-r}Q${x+bw},${bottom} ${x+bw},${bottom-r}V${top}Z`;};
  const hv=hover;
  return <div ref={wrap} style={{position:"relative",width:"100%"}}>
    <svg className="chart-svg" width={W} height={height} role="img" aria-label="Runs per period: successful above the line, failed below">
      {upTicks.map(t=><g key={"u"+t}><line className="grid" x1={padL} x2={W-padR} y1={yUp(t)} y2={yUp(t)} strokeDasharray="3 4"/><text x={padL-8} y={yUp(t)+4} textAnchor="end">{t}</text></g>)}
      {dnTicks.map(t=><g key={"d"+t}><line className="grid" x1={padL} x2={W-padR} y1={yDn(t)} y2={yDn(t)} strokeDasharray="3 4"/><text x={padL-8} y={yDn(t)+4} textAnchor="end" style={{fill:"var(--badText)"}}>{t}</text></g>)}
      <line className="grid" x1={padL} x2={W-padR} y1={mid} y2={mid} style={{stroke:"var(--border2)"}}/><text x={padL-8} y={mid+4} textAnchor="end">0</text>
      {labels.map((l,i)=>{
        const x=padL+i*step+(step-bw)/2;const s=success[i]||0,f=failed[i]||0;
        const dim=(selected!=null&&selected!==i)||(hv!=null&&hv!==i);
        return <g key={i} style={{opacity:dim?.45:1,transition:"opacity .15s"}}>
          {s>0&&<path className="bar" style={{animationDelay:`${i*stagger}ms`}} d={up(x,yUp(s),mid-1)} fill="var(--ok)"/>}
          {f>0&&<path className="bar bar-down" style={{animationDelay:`${i*stagger+120}ms`}} d={dn(x,mid+1,yDn(f))} fill="var(--bad)"/>}
          {i%every===0&&<text x={padL+i*step+step/2} y={height-8} textAnchor="middle">{l}</text>}
          <rect className="hit" x={padL+i*step} y={padT} width={step} height={ih} fill="transparent"
            tabIndex={onPick?0:-1} role={onPick?"button":undefined} aria-label={`${l}: ${s} successful, ${f} failed`}
            onMouseEnter={()=>setHover(i)} onMouseLeave={()=>setHover(null)} onFocus={()=>setHover(i)} onBlur={()=>setHover(null)}
            onClick={()=>onPick&&onPick(i)} onKeyDown={e=>{if((e.key==="Enter"||e.key===" ")&&onPick){e.preventDefault();onPick(i);}}}/>
        </g>;
      })}
    </svg>
    {hv!=null&&(()=>{
      const cx=padL+hv*step+step/2;const left=Math.min(Math.max(cx-80,0),W-180);
      const s=success[hv]||0,f=failed[hv]||0,t=s+f;
      return <div className="tip" style={{left,top:Math.max(0,yUp(s)-100)}}>
        <div style={{fontWeight:700,marginBottom:2}}>{labels[hv]}</div>
        <div style={{display:"flex",alignItems:"center",gap:6}}><i style={{width:8,height:8,borderRadius:2,background:"var(--ok)",display:"inline-block"}}/>Successful <b style={{marginLeft:"auto",paddingLeft:12}}>{s}</b></div>
        <div style={{display:"flex",alignItems:"center",gap:6}}><i style={{width:8,height:8,borderRadius:2,background:"var(--bad)",display:"inline-block"}}/>Failed <b style={{marginLeft:"auto",paddingLeft:12}}>{f}</b></div>
        <div style={{opacity:.75,marginTop:2}}>{t} total{t?` · ${Math.round(s/t*100)}% success`:""}</div>
        {onPick&&t>0&&<div style={{opacity:.75}}>{pickHint}</div>}
      </div>;
    })()}
  </div>;
}