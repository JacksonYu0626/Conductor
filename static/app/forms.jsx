// ─── forms.jsx ───────────────────────────────────────────────────────────────
// Every create/edit form. The save logic and payloads are unchanged from the
// previous version of the app; only the layout and styling are new.

const DAYS=["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"];
const WEEKS=["start","end"];
const WEEK_LABELS={"start":"Start of month","end":"End of month","1st":"1st week","2nd":"2nd week","3rd":"3rd week","4th":"4th week"};
const QUARTER_LABELS={"start":"Start of quarter","end":"End of quarter","1st":"1st week","2nd":"2nd week","3rd":"3rd week","4th":"4th week"};
const getWeekLabel=(freq,val)=>(freq==="quarterly"?QUARTER_LABELS:WEEK_LABELS)[val]||val;
const RECURRENCES=["once","hourly","daily","weekly","monthly","quarterly"];
const TIMEZONES=["America/Los_Angeles","America/Denver","America/Chicago","America/New_York","UTC"];
const cap=s=>s?s.charAt(0).toUpperCase()+s.slice(1):s;
const utcToLocalDate=(u,tz)=>u?new Date(u+"Z").toLocaleDateString("en-CA",{timeZone:tz||TZ}):"";
const utcToLocalTime=(u,tz,fallback)=>u?new Date(u+"Z").toLocaleTimeString("en-US",{hour:"2-digit",minute:"2-digit",hour12:false,timeZone:tz||TZ}).replace(" ","").replace(/^24:/,"00:"):fallback;

function Field({label,hint,children,style}){
  return <div className="form-row" style={style}>{label&&<label className="lbl">{label}</label>}{children}{hint&&<p className="hint">{hint}</p>}</div>;
}
function RecurrencePicker({value,onChange}){
  return <div style={{display:"flex",gap:6,flexWrap:"wrap"}}>{RECURRENCES.map(v=><button key={v} type="button" className={"choice"+(value===v?" on":"")} style={{flex:"1 1 80px"}} onClick={()=>onChange(v)}>{v==="once"?"One time":cap(v)}</button>)}</div>;
}
function DayPicker({days,toggle}){
  return <div style={{display:"flex",flexWrap:"wrap",gap:6}}>{DAYS.map(d=><button key={d} type="button" className={"daybtn"+(days.includes(d)?" on":"")} onClick={()=>toggle(d)} aria-pressed={days.includes(d)}>{d.slice(0,3)}</button>)}</div>;
}
function WeekPicker({freq,value,onChange}){
  return <div style={{display:"flex",gap:6}}>{WEEKS.map(w=><button key={w} type="button" className={"choice"+(value===w?" on":"")} onClick={()=>onChange(w)}>{getWeekLabel(freq,w)}</button>)}</div>;
}
function TzSelect({value,onChange}){return <select className="field" value={value} onChange={e=>onChange(e.target.value)}>{TIMEZONES.map(tz=><option key={tz} value={tz}>{tz}</option>)}</select>;}
function HourlyOptions({form,set,toggleDay}){
  return <>
    <div className="grid3 form-row">
      <div><label className="lbl">From</label><TimePicker value={form.run_time_local||"08:00"} onChange={v=>set("run_time_local",v)}/></div>
      <div><label className="lbl">To</label><TimePicker value={form.hourly_end_time||"17:00"} onChange={v=>set("hourly_end_time",v)}/></div>
      <div><label className="lbl">Every (hours)</label><input className="field" type="number" min="1" max="12" value={form.interval_hours} onChange={e=>set("interval_hours",+e.target.value)}/></div>
    </div>
    <Field label="On these days (optional)" hint="Leave blank to run Monday–Friday (default). Select specific days, or select all 7 to run every day."><DayPicker days={form.days_of_week} toggle={toggleDay}/></Field>
  </>;
}
function ToggleSection({on,onToggle,title,icon="sharepoint",children,locked}){
  const tog=locked?()=>{}:onToggle;
  return <div className="section-box" style={{padding:0,overflow:"hidden"}}>
    <div style={{display:"flex",alignItems:"center",justifyContent:"space-between",padding:"12px 14px",cursor:locked?"default":"pointer",background:on?"var(--accentSoft)":"var(--surface2)"}} onClick={tog} title={locked?"Only the owner can turn this on or off":undefined}>
      <span style={{display:"flex",alignItems:"center",gap:8,fontWeight:600,fontSize:13.5,color:on?"var(--accentText)":"var(--text)"}}><Icon name={icon} size={15}/>{title}{locked&&<Icon name="lock" size={13}/>}</span>
      <Switch on={on} onChange={tog} disabled={locked} label={title}/>
    </div>
    {on&&<div style={{padding:14,borderTop:"1px solid var(--border)"}}>{children}</div>}
  </div>;
}
function OutputFilesEditor({mode,rows,update,add,remove,placeholderPath}){
  const tab=mode==="update_tab";
  return <>
    {(tab?rows.slice(0,1):rows).map((row,i)=><div key={i} className="section-box tint" style={{padding:12,marginBottom:8}}>
      <div style={{display:"flex",alignItems:"center",justifyContent:"space-between",marginBottom:8}}>
        <span className="small" style={{fontWeight:700,color:"var(--text3)"}}>{tab?"Source → workbook":`File ${i+1}`}</span>
        {!tab&&<button type="button" className="btn btn-quiet btn-sm btn-icon" onClick={()=>remove(i)} disabled={rows.length===1} aria-label="Remove file"><Icon name="x" size={14}/></button>}
      </div>
      <label className="lbl">{tab?"Local source file (.csv/.xlsx)":"Local file path"}</label>
      <input className="field mono" value={row.path} onChange={e=>update(i,"path",e.target.value)} placeholder={placeholderPath} style={{marginBottom:8}}/>
      <label className="lbl">{tab?"Destination workbook (.xlsx full path) *":"Destination folder *"}</label>
      <input className="field mono" value={row.folder} onChange={e=>update(i,"folder",e.target.value)} placeholder={tab?"/Shared Documents/Reports/Summary.xlsx":"/Shared Documents/Reports/{MON}_{YYYY}"}/>
    </div>)}
    {!tab&&<button type="button" className="link-btn" onClick={add} style={{fontSize:13,margin:"2px 0 8px"}}>+ Add another file</button>}
  </>;
}
function UploadModeEditor({form,set}){
  return <>
    <Field label="Upload mode"><div style={{display:"flex",gap:8}}>{[["replace","Replace whole file"],["update_tab","Update specific tab"]].map(([v,l])=><button key={v} type="button" className={"choice"+(form.upload_mode===v?" on":"")} onClick={()=>set("upload_mode",v)}>{l}</button>)}</div></Field>
    {form.upload_mode==="update_tab"&&<div className="section-box tint">
      <Field label="Target sheet / tab name"><input className="field" value={form.target_sheet||""} onChange={e=>set("target_sheet",e.target.value)} placeholder="e.g. Sheet1"/></Field>
      <Field label="Target table name *" hint="The Table name is the Excel ListObject name (Table Design → Table Name), not the sheet name. Source column headers must match the Table's headers." style={{marginBottom:0}}><input className="field" value={form.target_table||""} onChange={e=>set("target_table",e.target.value)} placeholder="e.g. Table1"/></Field>
    </div>}
  </>;
}
const TOKENS_HINT=<>Tokens: <code>{"{YYYY}"}</code> <code>{"{MM}"}</code> <code>{"{DD}"}</code> <code>{"{MON}"}</code> <code>{"{QUARTER}"}</code></>;
function useOutputFiles(initial){
  const [rows,setRows]=useState(()=>{
    const lines=(initial||"").split("\n").map(l=>l.trim()).filter(Boolean);
    if(!lines.length)return [{path:"",folder:""}];
    return lines.map(l=>{const [p,f]=l.split("->");return {path:(p||"").trim(),folder:(f||"").trim()};});
  });
  return {rows,
    add:()=>setRows(r=>[...r,{path:"",folder:""}]),
    remove:i=>setRows(r=>r.filter((_,x)=>x!==i)),
    update:(i,k,v)=>setRows(r=>r.map((row,x)=>x===i?{...row,[k]:v}:row)),
    serialize:()=>rows.filter(r=>r.path.trim()).map(r=>r.folder.trim()?`${r.path.trim()} -> ${r.folder.trim()}`:r.path.trim()).join("\n")};
}
// Site picker; locked (owner's site, read-only) for people the schedule is shared with
function SiteSelect({value,onChange,sites,locked,lockedName,full=true}){
  if(locked)return <select className="field" value={value||""} disabled title="Only the owner can change the SharePoint site"><option value={value||""}>{lockedName||(value?`Site #${value}`:"— None —")}</option></select>;
  return <select className="field" value={value||""} onChange={e=>onChange(+e.target.value||null)}><option value="">{full?"— Select a registered site —":"— Select a site —"}</option>{sites.map(s=><option key={s.id} value={s.id}>{full?`${s.name} — ${s.site_url}`:s.name}</option>)}</select>;
}
function SaveFooter({onClose,onSave,loading,label="Save schedule",extra}){
  return <>{extra}<span style={{flex:1}}/><button className="btn" onClick={onClose}>Cancel</button><button className="btn btn-primary" onClick={onSave} disabled={loading}>{loading?<><Spinner size={14} color="#fff"/>Saving…</>:label}</button></>;
}

// ─── Script schedule ──────────────────────────────────────────────────────────
function ScheduleFormModal({schedule,scripts,onSave,onClose,presetScriptId}){
  const [form,setForm]=useState(schedule?{...schedule,frequency:schedule.frequency||schedule.recurrence||"daily",days_of_week:schedule.days_of_week||[],recipients:schedule.recipients||[],start_date:schedule.start_date?String(schedule.start_date).split("T")[0]:"",sharepoint_site_id:schedule.sharepoint_site_id||null,sharepoint_folder:schedule.sharepoint_folder||"",output_file_path:schedule.output_file_path||"",append_timestamp_to_filename:!!schedule.append_timestamp_to_filename,upload_mode:schedule.upload_mode||"replace",target_sheet:schedule.target_sheet||"",target_table:schedule.target_table||"",sp_enabled:!!(schedule.sharepoint_site_id),timezone:schedule.timezone||TZ,interval_hours:schedule.interval_hours||1,hourly_end_time:schedule.hourly_end_time||"17:00",run_date:utcToLocalDate(schedule.run_at_utc,schedule.timezone),run_time_local:utcToLocalTime(schedule.run_at_utc,schedule.timezone,"08:00")}
    :{script_id:presetScriptId||scripts[0]?.id||"",frequency:"daily",run_time:"08:00",days_of_week:[],week_of_month:"start",start_date:"",is_active:true,email_on_success:true,email_on_failure:true,recipients:[],sharepoint_site_id:null,sharepoint_folder:"",output_file_path:"",append_timestamp_to_filename:false,upload_mode:"replace",target_sheet:"",target_table:"",sp_enabled:false,timezone:TZ,interval_hours:1,hourly_end_time:"17:00",run_date:"",run_time_local:"08:00"});
  const [loading,setLoading]=useState(false);const [err,setErr]=useState("");
  const [spSites,setSpSites]=useState([]);
  const {openTestRun}=useApp();
  const shared=schedule?.my_access==="edit";   // shared with me — can't change script or site
  useEffect(()=>{api.getSpSites().then(setSpSites).catch(()=>{});},[]);
  const out=useOutputFiles(form.output_file_path);
  const scriptOpts=schedule&&schedule.script_id&&!scripts.find(s=>s.id===schedule.script_id)?[...scripts,{id:schedule.script_id,name:schedule.script_name||`Script #${schedule.script_id}`}]:scripts;
  const set=(k,v)=>setForm(f=>({...f,[k]:v}));
  const toggleDay=d=>set("days_of_week",form.days_of_week.includes(d)?form.days_of_week.filter(x=>x!==d):[...form.days_of_week,d]);
  const save=async()=>{
    if(!form.script_id){setErr("Please select a script.");return;}
    if(form.frequency==="once"&&!form.run_date){setErr("Run date/time is required for one-time schedules.");return;}
    if(form.sp_enabled&&!form.sharepoint_site_id){setErr("Please select a SharePoint site, or turn off SharePoint posting.");return;}
    const isUpdateTab=form.upload_mode==="update_tab";
    const outputFilePath=out.serialize();
    if(form.sp_enabled&&!outputFilePath){setErr(isUpdateTab?"Please provide the source file and destination workbook path.":"Please provide at least one output file path, or turn off SharePoint posting.");return;}
    if(form.sp_enabled&&isUpdateTab){
      if(!form.target_table?.trim()){setErr("Target Table Name is required for Update specific tab mode.");return;}
      const first=out.rows.find(r=>r.path.trim());
      if(!first||!first.folder.trim()){setErr("Update specific tab mode needs both a source file and a destination .xlsx path.");return;}
    }
    if(form.sp_enabled&&!isUpdateTab&&out.rows.some(r=>r.path.trim()&&!r.folder.trim())){setErr("Please provide a destination folder for each output file.");return;}
    setLoading(true);setErr("");
    const {sp_enabled:_sp,...formRest}=form;
    const run_at_local=form.run_date&&form.run_time_local?`${form.run_date}T${form.run_time_local}`:"";
    const payload={...formRest,run_at_local,sharepoint_site_id:form.sp_enabled?form.sharepoint_site_id:null,sharepoint_folder:form.sp_enabled?form.sharepoint_folder:null,output_file_path:form.sp_enabled?outputFilePath:null,append_timestamp_to_filename:form.sp_enabled&&!isUpdateTab?form.append_timestamp_to_filename:false,upload_mode:form.sp_enabled?(form.upload_mode||"replace"):"replace",target_sheet:form.sp_enabled&&isUpdateTab?(form.target_sheet||"").trim()||null:null,target_table:form.sp_enabled&&isUpdateTab?(form.target_table||"").trim()||null:null};
    try{const r=schedule?await api.updateScriptSchedule(schedule.id,payload):await api.createScriptSchedule(payload);onSave(r);}catch(e){setErr(e.message);}finally{setLoading(false);}
  };
  const testBtn=schedule&&form.script_id?<button type="button" className="btn" onClick={()=>openTestRun({id:form.script_id,name:schedule.script_name||schedule.name},true)} title="Run the script once now, without changing the schedule"><Icon name="play" size={14}/>Test run</button>:null;
  return <Modal title={schedule?"Edit script schedule":"New script schedule"} sub={schedule?(schedule.script_name||schedule.name):"Runs a registered Python script on a schedule"} onClose={onClose} width={600}
    footer={<SaveFooter onClose={onClose} onSave={save} loading={loading} extra={testBtn}/>}>
    {schedule&&<SharedNote s={schedule}/>}
    <Field label="Script"><select className="field" value={form.script_id} onChange={e=>set("script_id",+e.target.value)} disabled={!!schedule}><option value="">Select a script…</option>{scriptOpts.map(s=><option key={s.id} value={s.id}>{s.name}</option>)}</select></Field>
    <Field label="Recurrence"><RecurrencePicker value={form.frequency} onChange={v=>set("frequency",v)}/></Field>
    {form.frequency==="weekly"&&<Field label="Days of week"><DayPicker days={form.days_of_week} toggle={toggleDay}/></Field>}
    {(form.frequency==="monthly"||form.frequency==="quarterly")&&<Field label={form.frequency==="quarterly"?"Quarterly timing":"Monthly timing"}><WeekPicker freq={form.frequency} value={form.week_of_month} onChange={v=>set("week_of_month",v)}/></Field>}
    {(form.frequency==="once"||form.frequency==="hourly")?<>
      <div className={form.frequency==="once"?"grid2 form-row":"form-row"}>
        <div><label className="lbl">{form.frequency==="once"?"Run date *":"Start date"}</label><input className="field" type="date" value={form.run_date||""} onChange={e=>set("run_date",e.target.value)}/>{form.frequency==="hourly"&&<p className="hint">Leave blank to start immediately</p>}</div>
        {form.frequency==="once"&&<div><label className="lbl">Run time *</label><TimePicker value={form.run_time_local||"08:00"} onChange={v=>set("run_time_local",v)}/></div>}
      </div>
      {form.frequency==="hourly"&&<HourlyOptions form={form} set={set} toggleDay={toggleDay}/>}
      <Field label="Timezone"><TzSelect value={form.timezone} onChange={v=>set("timezone",v)}/></Field>
    </>:<div className="grid2 form-row">
      <div><label className="lbl">Start date</label><input className="field" type="date" value={form.start_date||""} onChange={e=>set("start_date",e.target.value)}/></div>
      <div><label className="lbl">Start time</label><TimePicker value={form.run_time||"08:00"} onChange={v=>set("run_time",v)}/></div>
    </div>}
    <div className="section-box tint">
      <div className="section-title"><Icon name="mail" size={15}/>Email notifications</div>
      <div style={{display:"flex",gap:18,marginBottom:10}}>
        <label className="check"><input type="checkbox" checked={form.email_on_success} onChange={e=>set("email_on_success",e.target.checked)}/>On success</label>
        <label className="check"><input type="checkbox" checked={form.email_on_failure} onChange={e=>set("email_on_failure",e.target.checked)}/>On failure</label>
      </div>
      {(form.email_on_success||form.email_on_failure)&&<><label className="lbl">Recipients</label><EmailPicker value={form.recipients} onChange={v=>set("recipients",v)}/></>}
    </div>
    <ToggleSection on={form.sp_enabled} onToggle={()=>set("sp_enabled",!form.sp_enabled)} title="Also post output to SharePoint" locked={shared}>
      <UploadModeEditor form={form} set={set}/>
      <label className="lbl">{form.upload_mode==="update_tab"?"Source file & destination workbook *":"Output file(s) *"}</label>
      <OutputFilesEditor mode={form.upload_mode} rows={out.rows} update={out.update} add={out.add} remove={out.remove} placeholderPath={"\\\\mpmfileserver01\\path\\report_{YYYY}{MM}{DD}.xlsx"}/>
      <p className="hint" style={{marginBottom:12}}>{form.upload_mode==="update_tab"?"Path the script writes its data to, and the existing SharePoint workbook to update in place. ":"Path the script writes each output to, and where it should be posted on SharePoint. "}{TOKENS_HINT}</p>
      <Field label="SharePoint site *" hint={shared?"Only the owner can change the site.":spSites.length===0?"No SharePoint sites registered yet. Add one on the SharePoint sites page.":null}>
        <SiteSelect value={form.sharepoint_site_id} onChange={v=>set("sharepoint_site_id",v)} sites={spSites} locked={shared} lockedName={schedule?.sharepoint_site_name}/>
      </Field>
      {form.upload_mode!=="update_tab"&&<label className="check" style={{marginBottom:8}}><input type="checkbox" checked={form.append_timestamp_to_filename} onChange={e=>set("append_timestamp_to_filename",e.target.checked)}/>Append timestamp to filename (e.g. report_20260611_143000.xlsx)</label>}
      <p className="hint">Make sure the destination folder is on a SharePoint <b>team site</b> (Shared Documents or another shared library) — personal OneDrive folders aren't supported.</p>
    </ToggleSection>
    <label className="check"><input type="checkbox" checked={form.is_active} onChange={e=>set("is_active",e.target.checked)}/>Schedule is active</label>
    <div style={{marginTop:14}}><ErrNote>{err}</ErrNote></div>
  </Modal>;
}

// ─── Tableau schedule ─────────────────────────────────────────────────────────
function TableauScheduleModal({schedule,dashboards,onSave,onClose,presetDashboardId}){
  const filtersToRows=f=>Object.entries(f||{}).map(([k,v])=>({k,v}));
  const rowsToFilters=rows=>Object.fromEntries(rows.filter(r=>r.k.trim()).map(r=>[r.k.trim(),r.v.trim()]));
  const isEdit=schedule&&schedule.schedule_type==="tableau";
  const [form,setForm]=useState(isEdit?{name:schedule.name||"",dashboard_id:schedule.dashboard_id||"",email_to:schedule.email_to||"",cc_to:schedule.cc_to||"",email_to_list:splitEmails(schedule.email_to),cc_to_list:splitEmails(schedule.cc_to),fmt:schedule.fmt||"pdf",recurrence:schedule.recurrence||"daily",interval_hours:schedule.interval_hours||1,hourly_end_time:schedule.hourly_end_time||"17:00",run_date:utcToLocalDate(schedule.run_at_utc,schedule.timezone),run_time_local:utcToLocalTime(schedule.run_at_utc,schedule.timezone,"10:00"),timezone:schedule.timezone||TZ,is_active:schedule.is_active!==false,email_on_success:schedule.email_on_success!==false,email_on_failure:schedule.email_on_failure!==false,days_of_week:schedule.days_of_week||[],week_of_month:schedule.week_of_month||"start",sharepoint_site_id:schedule.sharepoint_site_id||null,sharepoint_folder:schedule.sharepoint_folder||"",sp_enabled:!!(schedule.sharepoint_site_id)}
    :{name:"",dashboard_id:presetDashboardId||dashboards[0]?.id||"",email_to:"",cc_to:"",email_to_list:[],cc_to_list:[],fmt:"pdf",recurrence:"daily",interval_hours:1,hourly_end_time:"17:00",run_date:"",run_time_local:"10:00",timezone:TZ,is_active:true,email_on_success:true,email_on_failure:true,days_of_week:[],week_of_month:"start",sharepoint_site_id:null,sharepoint_folder:"",sp_enabled:false});
  const [filterRows,setFilterRows]=useState(filtersToRows(schedule?.filters||{}));
  const [loading,setLoading]=useState(false);const [err,setErr]=useState("");
  const [spSites,setSpSites]=useState([]);
  const shared=isEdit&&schedule.my_access==="edit";   // shared with me — can't change dashboard or site
  useEffect(()=>{api.getSpSites().then(setSpSites).catch(()=>{});},[]);
  const set=(k,v)=>setForm(f=>({...f,[k]:v}));
  const toggleDay=d=>set("days_of_week",form.days_of_week.includes(d)?form.days_of_week.filter(x=>x!==d):[...form.days_of_week,d]);
  const dashOpts=isEdit&&schedule.dashboard_id&&!dashboards.find(d=>d.id===schedule.dashboard_id)?[...dashboards,{id:schedule.dashboard_id,name:schedule.dashboard_name||`Dashboard #${schedule.dashboard_id}`}]:dashboards;
  const setRow=(i,field,val)=>setFilterRows(rows=>rows.map((r,idx)=>idx===i?{...r,[field]:val}:r));
  const save=async()=>{if(!form.email_to_list?.length&&!form.email_to){setErr("Email recipient is required.");return;}if(form.recurrence==="once"&&!form.run_date){setErr("Run date/time is required for one-time schedules.");return;}if(form.recurrence==="weekly"&&!form.days_of_week.length){setErr("Select at least one day of the week.");return;}setLoading(true);setErr("");
    try{const run_at_local=form.run_date&&form.run_time_local?`${form.run_date}T${form.run_time_local}`:"";const {sp_enabled:_sp,...formRest}=form;const payload={...formRest,run_at_local,filters:rowsToFilters(filterRows),email_to:(form.email_to_list||[]).join("; ")||form.email_to,cc_to:(form.cc_to_list||[]).join("; ")||form.cc_to,schedule_type:"tableau",sharepoint_site_id:form.sp_enabled?form.sharepoint_site_id:null,sharepoint_folder:form.sp_enabled?form.sharepoint_folder:null};const r=isEdit?await api.updateTableauSchedule(schedule.id,payload):await api.createTableauSchedule(payload);onSave(r);}catch(e){setErr(e.message);}finally{setLoading(false);}};
  return <Modal title={isEdit?"Edit Tableau schedule":"New Tableau schedule"} sub="Emails a snapshot of a Tableau view on a schedule" onClose={onClose} width={600}
    footer={<SaveFooter onClose={onClose} onSave={save} loading={loading}/>}>
    {isEdit&&<SharedNote s={schedule}/>}
    <Field label="Schedule name"><input className="field" value={form.name} onChange={e=>set("name",e.target.value)} placeholder="Monthly Membership Dashboard"/></Field>
    <Field label="Dashboard (optional)" hint={shared?"Only the owner can change the dashboard.":null}><select className="field" value={form.dashboard_id||""} disabled={shared} onChange={e=>set("dashboard_id",+e.target.value||"")}><option value="">— Link to a registered dashboard —</option>{dashOpts.map(d=><option key={d.id} value={d.id}>{d.name}</option>)}</select></Field>
    <div className="section-box tint">
      <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:6}}>
        <span className="section-title" style={{margin:0}}><Icon name="filter" size={15}/>Filters & parameters</span>
        <button type="button" className="btn btn-sm" onClick={()=>setFilterRows(r=>[...r,{k:"",v:""}])}><Icon name="plus" size={13}/>Add</button>
      </div>
      <p className="hint" style={{margin:"0 0 8px"}}>Use the exact name as shown on the dashboard, e.g. <code>Company ID</code>.</p>
      {filterRows.length===0&&<div className="small muted" style={{textAlign:"center",padding:"6px 0"}}>No filters configured</div>}
      {filterRows.map((row,i)=><div key={i} style={{display:"grid",gridTemplateColumns:"1fr 1fr auto",gap:6,marginBottom:6}}>
        <input className="field" value={row.k} onChange={e=>setRow(i,"k",e.target.value)} placeholder="Company ID or HPCODE"/>
        <input className="field" value={row.v} onChange={e=>setRow(i,"v",e.target.value)} placeholder="HCLA or LAMC"/>
        <button type="button" className="btn btn-icon" onClick={()=>setFilterRows(r=>r.filter((_,x)=>x!==i))} aria-label="Remove filter"><Icon name="x" size={14}/></button>
      </div>)}
    </div>
    <div className="section-box tint">
      <div className="section-title"><Icon name="mail" size={15}/>Email</div>
      <Field label="Send to *"><EmailPicker value={form.email_to_list||[]} onChange={v=>set("email_to_list",v)}/></Field>
      <Field label="CC (optional)" style={{marginBottom:0}}><EmailPicker value={form.cc_to_list||[]} onChange={v=>set("cc_to_list",v)}/></Field>
    </div>
    <Field label="Format"><Seg wide value={form.fmt} onChange={v=>set("fmt",v)} options={[["pdf","PDF"],["png","PNG"]]}/></Field>
    <Field label="Recurrence"><RecurrencePicker value={form.recurrence} onChange={v=>set("recurrence",v)}/></Field>
    {form.recurrence==="weekly"&&<Field label="Days of week *"><DayPicker days={form.days_of_week} toggle={toggleDay}/></Field>}
    {(form.recurrence==="monthly"||form.recurrence==="quarterly")&&<Field label={form.recurrence==="quarterly"?"Quarterly timing":"Monthly timing"}><WeekPicker freq={form.recurrence} value={form.week_of_month} onChange={v=>set("week_of_month",v)}/></Field>}
    <div className={form.recurrence==="hourly"?"form-row":"grid3 form-row"}>
      <div><label className="lbl">{form.recurrence==="once"?"Run date *":"Start date"}</label><input className="field" type="date" value={form.run_date||""} onChange={e=>set("run_date",e.target.value)}/></div>
      {form.recurrence!=="hourly"&&<div><label className="lbl">{form.recurrence==="once"?"Run time *":"Start time"}</label><TimePicker value={form.run_time_local||"10:00"} onChange={v=>set("run_time_local",v)}/></div>}
      {form.recurrence!=="hourly"&&<div><label className="lbl">Timezone</label><TzSelect value={form.timezone} onChange={v=>set("timezone",v)}/></div>}
    </div>
    {form.recurrence==="hourly"&&<><HourlyOptions form={form} set={set} toggleDay={toggleDay}/><Field label="Timezone"><TzSelect value={form.timezone} onChange={v=>set("timezone",v)}/></Field></>}
    <ToggleSection on={form.sp_enabled} onToggle={()=>set("sp_enabled",!form.sp_enabled)} title="Also post to SharePoint" locked={shared}>
      <Field label="SharePoint site *" hint={shared?"Only the owner can change the site.":spSites.length===0?"No SharePoint sites registered yet. Add one on the SharePoint sites page.":null}>
        <SiteSelect value={form.sharepoint_site_id} onChange={v=>set("sharepoint_site_id",v)} sites={spSites} locked={shared} lockedName={schedule?.sharepoint_site_name}/>
      </Field>
      <Field label="Destination folder" hint={<>{TOKENS_HINT} — filename is auto-generated from schedule name + date.</>} style={{marginBottom:0}}><input className="field mono" value={form.sharepoint_folder||""} onChange={e=>set("sharepoint_folder",e.target.value)} placeholder="/Reports/{MON}_{YYYY}"/></Field>
    </ToggleSection>
    <label className="check"><input type="checkbox" checked={form.is_active} onChange={e=>set("is_active",e.target.checked)}/>Schedule is active</label>
    <div style={{marginTop:14}}><ErrNote>{err}</ErrNote></div>
  </Modal>;
}

// ─── SharePoint upload schedule ───────────────────────────────────────────────
function SpScheduleModal({schedule,sites,onSave,onClose,presetSiteId}){
  const [form,setForm]=useState(schedule?{
    name:schedule.name||"",sharepoint_site_id:schedule.sharepoint_site_id||"",append_timestamp_to_filename:!!schedule.append_timestamp_to_filename,
    notify_email_to_list:splitEmails(schedule.notify_email_to),notify_cc_to_list:splitEmails(schedule.notify_cc_to),
    email_on_success:schedule.email_on_success!==false,email_on_failure:schedule.email_on_failure!==false,
    recurrence:schedule.recurrence||"once",interval_hours:schedule.interval_hours||1,hourly_end_time:schedule.hourly_end_time||"17:00",
    run_date:utcToLocalDate(schedule.run_at_utc,schedule.timezone),run_time_local:utcToLocalTime(schedule.run_at_utc,schedule.timezone,"09:00"),
    timezone:schedule.timezone||TZ,
    days_of_week:typeof schedule.days_of_week==="string"?schedule.days_of_week.split(",").map(d=>d.trim()).filter(Boolean):(schedule.days_of_week||[]),
    week_of_month:schedule.week_of_month||"start",upload_mode:schedule.upload_mode||"replace",target_sheet:schedule.target_sheet||"",target_table:schedule.target_table||"",is_active:schedule.is_active!==false
  }:{
    name:"",sharepoint_site_id:presetSiteId||sites[0]?.id||"",append_timestamp_to_filename:false,upload_mode:"replace",target_sheet:"",target_table:"",
    notify_email_to_list:[],notify_cc_to_list:[],email_on_success:true,email_on_failure:true,
    recurrence:"once",interval_hours:1,hourly_end_time:"17:00",run_date:"",run_time_local:"09:00",timezone:TZ,days_of_week:[],week_of_month:"start",is_active:true
  });
  const out=useOutputFiles(schedule?.output_file_path||"");
  const [loading,setLoading]=useState(false);const [err,setErr]=useState("");
  const shared=schedule?.my_access==="edit";   // shared with me — can't change the site
  const set=(k,v)=>setForm(f=>({...f,[k]:v}));
  const toggleDay=d=>set("days_of_week",form.days_of_week.includes(d)?form.days_of_week.filter(x=>x!==d):[...form.days_of_week,d]);
  const save=async()=>{
    if(!form.name||!form.sharepoint_site_id){setErr("Name and SharePoint site are required.");return;}
    if(out.rows.every(r=>!r.path.trim())){setErr("At least one source file path is required.");return;}
    if(out.rows.some(r=>r.path.trim()&&!r.folder.trim())){setErr("Please provide a destination for each source file.");return;}
    if(form.upload_mode==="update_tab"){
      if(!form.target_table?.trim()){setErr("Target Table Name is required for Update specific tab mode.");return;}
      const bad=out.rows.find(r=>r.folder.trim()&&!/\.(xlsx|xlsm)$/i.test(r.folder.trim()));
      if(bad){setErr("Destination workbook must end in .xlsx or .xlsm (include the filename in the destination path).");return;}
    }
    if(form.recurrence==="once"&&!form.run_date){setErr("Run date/time is required.");return;}
    if(form.recurrence==="weekly"&&!form.days_of_week.length){setErr("Select at least one day.");return;}
    setLoading(true);setErr("");
    try{
      const run_at_local=form.run_date&&form.run_time_local?`${form.run_date}T${form.run_time_local}`:"";
      const {run_date:_d,run_time_local:_t,notify_email_to_list:_nl,notify_cc_to_list:_cl,...rest}=form;
      const b={...rest,sharepoint_site_id:+form.sharepoint_site_id,run_at_local,days_of_week:form.days_of_week.join(","),output_file_path:out.serialize(),
        source_path:null,source_folder:null,filename_pattern:null,date_format:null,destination_filename:null,upload_mode:form.upload_mode||"replace",
        target_sheet:form.upload_mode==="update_tab"?(form.target_sheet||"").trim()||null:null,target_table:form.upload_mode==="update_tab"?(form.target_table||"").trim()||null:null,
        notify_email_to:(_nl||[]).join("; ")||null,notify_cc_to:(_cl||[]).join("; ")||null};
      const r=schedule?await api.updateSpSchedule(schedule.id,b):await api.createSpSchedule(b);onSave(r);
    }catch(e){setErr(e?.message||String(e));}finally{setLoading(false);}
  };
  return <Modal title={schedule?"Edit SharePoint schedule":"New SharePoint schedule"} sub="Uploads files to a SharePoint site on a schedule" onClose={onClose} width={600}
    footer={<SaveFooter onClose={onClose} onSave={save} loading={loading}/>}>
    {schedule&&<SharedNote s={schedule}/>}
    <Field label="Schedule name *"><input className="field" value={form.name} onChange={e=>set("name",e.target.value)} placeholder="Monthly Eligibility Upload"/></Field>
    <UploadModeEditor form={form} set={set}/>
    <label className="lbl">{form.upload_mode==="update_tab"?"Source file *":"Output file(s) *"}</label>
    <OutputFilesEditor mode={form.upload_mode} rows={out.rows} update={out.update} add={out.add} remove={out.remove} placeholderPath={"\\\\mpmfileserver01\\path\\your_data.csv"}/>
    <p className="hint" style={{marginBottom:14}}>{form.upload_mode==="update_tab"?"Path to the source file (CSV or XLSX), and the full SharePoint path to the destination workbook including filename.":<>Path to the file, and the destination folder on SharePoint. {TOKENS_HINT}</>}</p>
    <Field label="SharePoint site *" hint={shared?"Only the owner can change the site.":sites.length===0?"No SharePoint sites registered yet. Add one on the SharePoint sites page.":null}>
      <SiteSelect full={false} value={form.sharepoint_site_id} onChange={v=>set("sharepoint_site_id",v||"")} sites={sites} locked={shared} lockedName={schedule?.sharepoint_site_name}/>
    </Field>
    {form.upload_mode!=="update_tab"&&<label className="check" style={{marginBottom:8}}><input type="checkbox" checked={form.append_timestamp_to_filename} onChange={e=>set("append_timestamp_to_filename",e.target.checked)}/>Append timestamp to filename (e.g. report_20260611_143000.xlsx)</label>}
    <p className="hint" style={{marginBottom:14}}>Make sure the destination folder is on a SharePoint <b>team site</b> — personal OneDrive folders aren't supported.</p>
    <Field label="Recurrence"><RecurrencePicker value={form.recurrence} onChange={v=>set("recurrence",v)}/></Field>
    {form.recurrence==="weekly"&&<Field label="Days of week *"><DayPicker days={form.days_of_week} toggle={toggleDay}/></Field>}
    {(form.recurrence==="monthly"||form.recurrence==="quarterly")&&<Field label={form.recurrence==="quarterly"?"Quarterly timing":"Monthly timing"}><WeekPicker freq={form.recurrence} value={form.week_of_month} onChange={v=>set("week_of_month",v)}/></Field>}
    <div className={form.recurrence==="hourly"?"form-row":"grid3 form-row"}>
      <div><label className="lbl">{form.recurrence==="once"?"Run date *":"Start date"}</label><input className="field" type="date" value={form.run_date||""} onChange={e=>set("run_date",e.target.value)}/></div>
      {form.recurrence!=="hourly"&&<div><label className="lbl">{form.recurrence==="once"?"Run time *":"Start time"}</label><TimePicker value={form.run_time_local||"09:00"} onChange={v=>set("run_time_local",v)}/></div>}
      {form.recurrence!=="hourly"&&<div><label className="lbl">Timezone</label><TzSelect value={form.timezone} onChange={v=>set("timezone",v)}/></div>}
    </div>
    {form.recurrence==="hourly"&&<><HourlyOptions form={form} set={set} toggleDay={toggleDay}/><Field label="Timezone"><TzSelect value={form.timezone} onChange={v=>set("timezone",v)}/></Field></>}
    <div className="section-box tint">
      <div className="section-title"><Icon name="mail" size={15}/>Email notifications</div>
      <div style={{display:"flex",gap:18,marginBottom:10}}>
        <label className="check"><input type="checkbox" checked={form.email_on_success} onChange={e=>set("email_on_success",e.target.checked)}/>On success</label>
        <label className="check"><input type="checkbox" checked={form.email_on_failure} onChange={e=>set("email_on_failure",e.target.checked)}/>On failure</label>
      </div>
      <Field label="Recipients"><EmailPicker value={form.notify_email_to_list||[]} onChange={v=>set("notify_email_to_list",v)}/></Field>
      <Field label="CC (optional)" style={{marginBottom:0}}><EmailPicker value={form.notify_cc_to_list||[]} onChange={v=>set("notify_cc_to_list",v)}/></Field>
    </div>
    <label className="check"><input type="checkbox" checked={form.is_active} onChange={e=>set("is_active",e.target.checked)}/>Schedule is active</label>
    <div style={{marginTop:14}}><ErrNote>{err}</ErrNote></div>
  </Modal>;
}

// ─── Scripts: register / edit ────────────────────────────────────────────────
const TIMEOUT_OPTIONS=[
  {v:"",l:"1 hour (default)"},{v:"1800",l:"30 minutes"},{v:"7200",l:"2 hours"},{v:"14400",l:"4 hours"},
  {v:"21600",l:"6 hours"},{v:"28800",l:"8 hours"},{v:"36000",l:"10 hours"},{v:"43200",l:"12 hours (max)"},
];
function ProdPathChecklist({ack,onAck,showAck}){
  const [open,setOpen]=useState(showAck);
  const li={marginBottom:6};
  return <div className="note note-info" style={{display:"block",marginBottom:14}}>
    <button type="button" onClick={()=>setOpen(o=>!o)} aria-expanded={open} style={{display:"flex",alignItems:"center",gap:8,width:"100%",border:"none",background:"none",padding:0,cursor:"pointer",color:"inherit",fontWeight:700,textAlign:"left"}}>
      <Icon name="info" size={16}/><span style={{flex:1}}>Before you upload: your script runs on the server, not your PC</span><Icon name={open?"chevU":"chevD"} size={15}/>
    </button>
    {open&&<div style={{marginTop:10,fontSize:12.5}}>
      <div style={li}><b>1. No drive letters.</b> The server doesn't have your <code>F:\</code>, <code>N:\</code> or <code>M:\</code> drives. Any file your script reads or saves must use the full network path, e.g. <code>{"\\\\mpmfileserver01\\..."}</code>. This includes paths in your <code>.env</code> file.</div>
      <div style={li}><b>2. Files next to your script are fine.</b> Conductor runs your script from its own folder, so a path like <code>templates/report.xlsx</code> works if that file is included in your zip.</div>
      <div style={li}><b>3. Include everything it needs.</b> Zip up the <code>.env</code>, config files, templates and any helper <code>.py</code> files along with your main script.</div>
      <div style={li}><b>4. Don't save output inside the script folder.</b> It gets cleared every time you upload a new version. Save reports to a network folder or use the SharePoint option on your schedule.</div>
      <div style={{marginBottom:showAck?10:0}}><b>5. The server needs access.</b> Conductor runs under a service account. If your script reads or writes a network folder or database it hasn't used before, ask the Conductor admin to confirm the service account has access.</div>
      {showAck&&<label className="check" style={{fontWeight:700,paddingTop:10,borderTop:"1px solid color-mix(in srgb,currentColor 20%,transparent)"}}><input type="checkbox" checked={ack} onChange={e=>onAck(e.target.checked)}/>I've checked my script for the items above</label>}
    </div>}
  </div>;
}
function ScriptFormModal({script,onSave,onClose,onDelete}){
  const [form,setForm]=useState(script?{name:script.name||"",description:script.description||"",category:script.category||"General",script_type:script.script_type||"script",entry_point:script.entry_point||"main.py",timeout_sec:script.timeout_sec?String(script.timeout_sec):""}:{name:"",description:"",category:"General",script_type:"script",entry_point:"main.py",timeout_sec:""});
  const [pathAck,setPathAck]=useState(!!script);
  const [warnResult,setWarnResult]=useState(null);
  const [file,setFile]=useState(null);
  const [conflict,setConflict]=useState(null);
  const [overwrite,setOverwrite]=useState(false);
  const [loading,setLoading]=useState(false);
  const [err,setErr]=useState("");
  const fileRef=useRef(null);
  const set=(k,v)=>setForm(f=>({...f,[k]:v}));
  useEffect(()=>{setConflict(null);setOverwrite(false);},[form.name]);
  const timeoutOpts=form.timeout_sec&&!TIMEOUT_OPTIONS.find(o=>o.v===form.timeout_sec)?[...TIMEOUT_OPTIONS,{v:form.timeout_sec,l:secStr(+form.timeout_sec)}]:TIMEOUT_OPTIONS;
  const doSave=async(forceOverwrite)=>{
    if(!form.name){setErr("Name is required.");return;}
    if(!script&&!file){setErr("Please select a .py or .zip file to upload.");return;}
    if(!script&&!pathAck){setErr("Please confirm your script is ready for the production server (see checklist above).");return;}
    setLoading(true);setErr("");
    try{
      if(script&&!file){
        const r=await api.updateScript(script.id,{name:form.name,description:form.description,category:form.category,script_type:form.script_type,entry_point:form.entry_point,timeout_sec:(form.script_type!=="app"&&form.timeout_sec)?+form.timeout_sec:null});onSave(r);return;
      }
      if(!forceOverwrite&&!script){
        const chk=await api.checkUpload(form.name);
        if(chk.exists){setConflict(chk);setLoading(false);return;}
      }
      const fd=new FormData();
      fd.append("name",form.name);fd.append("description",form.description||"");
      fd.append("category",form.category||"General");fd.append("script_type",form.script_type||"script");
      fd.append("entry_point",form.entry_point||"main.py");
      fd.append("overwrite",(forceOverwrite||overwrite||!!script)?"true":"false");
      if(form.script_type!=="app"&&form.timeout_sec)fd.append("timeout_sec",String(form.timeout_sec));
      fd.append("file",file);
      const r=await api.registerScript(fd);
      if(r.path_warnings&&r.path_warnings.length){setWarnResult(r);return;}
      onSave(r);
    }catch(e){setErr(e.message);}finally{setLoading(false);}
  };
  if(warnResult)return <Modal title="Script saved — check these paths" onClose={()=>onSave(warnResult)} width={620}
    footer={<button className="btn btn-primary" onClick={()=>onSave(warnResult)}>Got it</button>}>
    <div className="note note-warn" style={{marginBottom:14}}><Icon name="warn" size={16}/><div><b>Possible local drive paths found.</b> Your script was saved, but these lines point to a drive letter (like <code>F:\</code> or <code>N:\</code>) that only exists on your own computer. The production server doesn't have these drives, so the script will likely fail when it reaches them. Change them to the full network path (e.g. <code>{"\\\\mpmfileserver01\\..."}</code>) and upload the files again.</div></div>
    <div className="console" style={{maxHeight:260,background:"var(--code)",color:"var(--text)"}}>{warnResult.path_warnings.join("\n")}</div>
  </Modal>;
  return <Modal title={script?"Edit script":"Register script"} sub={script?script.name:"Upload a .py file or a .zip of your project"} onClose={onClose} width={600}
    footer={!conflict&&<>
      {script&&onDelete&&<button className="btn btn-danger" onClick={()=>onDelete(script)}><Icon name="trash" size={14}/>Delete</button>}
      <span style={{flex:1}}/>
      <button className="btn" onClick={onClose}>Cancel</button>
      <button className="btn btn-primary" onClick={()=>doSave(false)} disabled={loading}>{loading?<><Spinner size={14} color="#fff"/>Uploading…</>:(script?"Save changes":"Register script")}</button>
    </>}>
    <Field label="Script name *"><input className="field" value={form.name} onChange={e=>set("name",e.target.value)} placeholder="e.g. Eligibility Data Update"/></Field>
    <Field label="Description"><textarea className="field" value={form.description} onChange={e=>set("description",e.target.value)} placeholder="What does this script do? Who uses it?"/></Field>
    <div className="grid2 form-row">
      <div><label className="lbl">Category</label><CategoryInput value={form.category} onChange={v=>set("category",v)}/></div>
      <div><label className="lbl">Entry point *</label><input className="field mono" value={form.entry_point} onChange={e=>set("entry_point",e.target.value)} placeholder="main.py"/></div>
    </div>
    <p className="hint" style={{marginTop:-8,marginBottom:14}}>The entry point is the file that runs. For zips, include any subfolder (e.g. <code>src/main.py</code>).</p>
    <Field label="Type"><div style={{display:"flex",gap:8}}>
      <button type="button" className={"choice"+(form.script_type!=="app"?" on":"")} onClick={()=>set("script_type","script")}>Script<small>Runs and finishes</small></button>
      <button type="button" className={"choice"+(form.script_type==="app"?" on":"")} onClick={()=>set("script_type","app")}>App<small>Long-running, no time limit</small></button>
    </div></Field>
    {form.script_type!=="app"&&<Field label="Max run time" hint="If the script is still running after this long, it is stopped and marked failed. Only raise it for scripts that genuinely take longer.">
      <select className="field" value={form.timeout_sec} onChange={e=>set("timeout_sec",e.target.value)}>{timeoutOpts.map(o=><option key={o.v} value={o.v}>{o.l}</option>)}</select>
    </Field>}
    <Field label={script?"Replace files (optional)":"Upload script files *"}>
      <button type="button" onClick={()=>fileRef.current?.click()} style={{width:"100%",border:`2px dashed ${file?"var(--accent)":"var(--border2)"}`,borderRadius:12,padding:"18px 16px",textAlign:"center",cursor:"pointer",background:file?"var(--accentSoft)":"transparent",color:file?"var(--accentText)":"var(--text2)"}}>
        <Icon name={file?"file":"upload"} size={20}/>
        <div style={{fontWeight:600,marginTop:4}}>{file?file.name:"Click to choose a file"}</div>
        <div className="small" style={{opacity:.8}}>{file?`${(file.size/1024).toFixed(1)} KB · click to change`:".py or .zip accepted"}</div>
      </button>
      <input ref={fileRef} type="file" accept=".py,.zip" style={{display:"none"}} onChange={e=>{setFile(e.target.files[0]||null);setConflict(null);setOverwrite(false);}}/>
      <p className="hint">Files are stored in your personal scripts folder on the server.</p>
    </Field>
    <ProdPathChecklist ack={pathAck} onAck={setPathAck} showAck={!script}/>
    {conflict&&!overwrite&&<div className="note note-warn" style={{display:"block",marginBottom:14}}>
      <div style={{fontWeight:700,marginBottom:4,display:"flex",alignItems:"center",gap:6}}><Icon name="warn" size={15}/>Folder already exists</div>
      <div style={{marginBottom:10}}>A folder at <code>{conflict.path}</code> already exists. Uploading will overwrite existing files.</div>
      <div style={{display:"flex",gap:8}}><button className="btn btn-sm" onClick={()=>{setConflict(null);setOverwrite(false);}}>Cancel</button><button className="btn btn-sm btn-primary" onClick={()=>{setOverwrite(true);doSave(true);}}>Yes, overwrite</button></div>
    </div>}
    <ErrNote>{err}</ErrNote>
  </Modal>;
}

// ─── Dashboards: register / edit (Tableau search as you type) ─────────────────
function DashboardFormModal({dashboard,onSave,onClose,onDelete}){
  const [form,setForm]=useState(dashboard?{...dashboard,additional_urls:dashboard.additional_urls||[],filters:dashboard.filters||{}}:{name:"",description:"",category:"General",view_url:"",additional_urls:[],fmt:"pdf",filters:{}});
  const [loading,setLoading]=useState(false);const [err,setErr]=useState("");
  const [urlMode,setUrlMode]=useState(dashboard?"manual":"search");
  const [q,setQ]=useState("");const [res,setRes]=useState([]);const [searching,setSearching]=useState(false);const [searched,setSearched]=useState("");
  const set=(k,v)=>setForm(f=>({...f,[k]:v}));
  // Search only when the Search button (or Enter) is pressed
  const doSearch=async()=>{
    const term=q.trim();if(!term||searching)return;
    setSearching(true);setRes([]);
    try{const r=await api.searchTableauViews(term);setRes(r.results||[]);}
    catch(e){setRes([{error:e.message}]);}
    finally{setSearching(false);setSearched(term);}
  };
  const pickView=v=>{const raw=v.viewUrl||v.contentUrl||"";set("view_url",raw.replace(/\/sheets/,""));if(!form.name&&(v.workbookName||v.name))set("name",v.workbookName||v.name);setRes([]);setQ("");setSearched("");};
  const extra=form.additional_urls||[];
  const save=async()=>{if(!form.name||!form.view_url){setErr("Name and Tableau URL are required.");return;}setLoading(true);setErr("");
    const body={...form,additional_urls:extra.map(u=>u.trim()).filter(Boolean)};
    try{const r=dashboard?await api.updateDashboard(dashboard.id,body):await api.createDashboard(body);onSave(r);}catch(e){setErr(e.message);}finally{setLoading(false);}};
  return <Modal title={dashboard?"Edit dashboard":"Register dashboard"} sub="A Tableau view Conductor can snapshot and email" onClose={onClose} width={600}
    footer={<>
      {dashboard&&onDelete&&<button className="btn btn-danger" onClick={()=>onDelete(dashboard)}><Icon name="trash" size={14}/>Delete</button>}
      <span style={{flex:1}}/><button className="btn" onClick={onClose}>Cancel</button>
      <button className="btn btn-primary" onClick={save} disabled={loading}>{loading?<><Spinner size={14} color="#fff"/>Saving…</>:(dashboard?"Save changes":"Register dashboard")}</button>
    </>}>
    <Field label="Tableau view *">
      <div style={{marginBottom:8}}><Seg value={urlMode} onChange={setUrlMode} options={[["search","Search Tableau"],["manual","Paste URL"]]}/></div>
      {urlMode==="manual"?<input className="field mono" value={form.view_url} onChange={e=>set("view_url",e.target.value)} placeholder="https://tableau.company.com/#/views/Workbook/View"/>
      :<div style={{position:"relative"}}>
        <div style={{display:"flex",gap:8}}>
          <div className="search" style={{maxWidth:"none",flex:1}}><Icon name="search" size={15}/><input className="field" value={q} onChange={e=>{setQ(e.target.value);if(searched)setSearched("");}} onKeyDown={e=>{if(e.key==="Enter"){e.preventDefault();doSearch();}}} placeholder="View or workbook name, then press Search" autoFocus/></div>
          <button type="button" className="btn btn-primary" onClick={doSearch} disabled={!q.trim()||searching}>{searching?<><Spinner size={14} color="#fff"/>Searching…</>:<><Icon name="search" size={15}/>Search</>}</button>
        </div>
        {res.length>0&&<div className="popover" style={{top:"calc(100% + 4px)",left:0,right:0,maxHeight:240,overflowY:"auto",padding:4}}>
          {res.map((v,i)=>v.error?<div key={i} className="small" style={{padding:10,color:"var(--badText)"}}>{v.error}</div>
            :<div key={i} className="menu-item" onClick={()=>pickView(v)}><Icon name="dashboards" size={15}/><div style={{minWidth:0}}><div style={{fontWeight:600}} className="trunc">{v.name}</div><div className="small muted mono trunc">{v.workbookName?v.workbookName+" · ":""}{v.contentUrl}</div></div></div>)}
        </div>}
        {!searching&&searched&&res.length===0&&<p className="hint">No views match “{searched}”.</p>}
      </div>}
      {form.view_url&&<div className="note note-info" style={{marginTop:8,padding:"8px 12px",wordBreak:"break-all"}}><Icon name="check" size={14}/><span className="mono small">{form.view_url}</span></div>}
    </Field>
    <Field label="Display name *"><input className="field" value={form.name} onChange={e=>set("name",e.target.value)} placeholder="Monthly Membership Dashboard"/></Field>
    <Field label="Description"><textarea className="field" value={form.description||""} onChange={e=>set("description",e.target.value)} placeholder="What does this dashboard show?" style={{minHeight:60}}/></Field>
    <div className="grid2 form-row">
      <div><label className="lbl">Category</label><CategoryInput value={form.category} onChange={v=>set("category",v)}/></div>
      <div><label className="lbl">Default format</label><Seg wide value={form.fmt||"pdf"} onChange={v=>set("fmt",v)} options={[["pdf","PDF"],["png","PNG"]]}/></div>
    </div>
    <Field label="Extra views (optional)" hint="Additional Tableau view URLs included in the same email.">
      {extra.map((u,i)=><div key={i} style={{display:"flex",gap:6,marginBottom:6}}><input className="field mono" value={u} onChange={e=>set("additional_urls",extra.map((x,j)=>j===i?e.target.value:x))} placeholder="https://tableau.company.com/#/views/Workbook/OtherView"/><button type="button" className="btn btn-icon" onClick={()=>set("additional_urls",extra.filter((_,j)=>j!==i))} aria-label="Remove view"><Icon name="x" size={14}/></button></div>)}
      <button type="button" className="link-btn" style={{fontSize:13}} onClick={()=>set("additional_urls",[...extra,""])}>+ Add a view</button>
    </Field>
    <ErrNote>{err}</ErrNote>
  </Modal>;
}

// ─── Dashboards: test send ────────────────────────────────────────────────────
function TestSendModal({dashboard,user,onClose}){
  const [toList,setToList]=useState(user?.email?[user.email]:[]);const [ccList,setCcList]=useState([]);const [fmt,setFmt]=useState(dashboard.fmt||"pdf");
  const [loading,setLoading]=useState(false);const [done,setDone]=useState(false);const [err,setErr]=useState("");
  const run=async()=>{if(!toList.length){setErr("Email recipient is required.");return;}setLoading(true);setErr("");
    try{await api.runDashboardNow(dashboard.id,{email_to:toList.join("; "),cc_to:ccList.join("; "),fmt});setDone(true);}catch(e){setErr(e.message);}finally{setLoading(false);}};
  if(done)return <Modal title="Test send queued" onClose={onClose} width={440} footer={<button className="btn btn-primary" onClick={onClose}>Done</button>}>
    <div style={{textAlign:"center",padding:"8px 0"}}>
      <div className="pop" style={{width:52,height:52,borderRadius:"50%",background:"var(--okSoft)",color:"var(--okText)",display:"flex",alignItems:"center",justifyContent:"center",margin:"0 auto 12px"}}><Icon name="mail" size={24}/></div>
      <div style={{fontWeight:600,marginBottom:6}}>{dashboard.name} is on its way</div>
      <div className="small muted">The view is being rendered as {fmt.toUpperCase()} and emailed to <b>{toList.join(", ")}</b>. It shows up in Run history as a Tableau run.</div>
    </div>
  </Modal>;
  return <Modal title="Test send" sub={dashboard.name} onClose={onClose} width={560}
    footer={<><button className="btn" onClick={onClose}>Cancel</button><button className="btn btn-primary" onClick={run} disabled={loading}>{loading?<><Spinner size={14} color="#fff"/>Sending…</>:<><Icon name="mail" size={15}/>Send now</>}</button></>}>
    <Field label="Send to *"><EmailPicker value={toList} onChange={setToList}/></Field>
    <Field label="CC (optional)"><EmailPicker value={ccList} onChange={setCcList}/></Field>
    <Field label="Format"><Seg wide value={fmt} onChange={setFmt} options={[["pdf","PDF"],["png","PNG"]]}/></Field>
    <ErrNote>{err}</ErrNote>
  </Modal>;
}

// ─── SharePoint site: register / edit ─────────────────────────────────────────
function SpSiteModal({site,onSave,onClose}){
  const [form,setForm]=useState(site?{name:site.name||"",site_url:site.site_url||"",site_type:site.site_type||"internal",tenant_id:site.tenant_id||"",client_id:site.client_id||"",client_secret:"",drive_id:site.drive_id||""}:{name:"",site_url:"",site_type:"internal",tenant_id:"",client_id:"",client_secret:"",drive_id:""});
  const [loading,setLoading]=useState(false);const [err,setErr]=useState("");
  const set=(k,v)=>setForm(f=>({...f,[k]:v}));
  const save=async()=>{
    if(!form.name||!form.site_url){setErr("Name and Site URL are required.");return;}
    if(form.site_type==="external"){if(!form.tenant_id||!form.client_id){setErr("Tenant ID and Client ID are required for external sites.");return;}if(!site&&!form.client_secret){setErr("Client Secret is required for external sites.");return;}}
    setLoading(true);setErr("");
    try{const b={...form};if(!b.client_secret)delete b.client_secret;if(!b.drive_id)delete b.drive_id;if(form.site_type==="internal"){delete b.tenant_id;delete b.client_id;delete b.client_secret;}const r=site?await api.updateSpSite(site.id,b):await api.createSpSite(b);onSave(r);}
    catch(e){setErr(e.message);}finally{setLoading(false);}
  };
  return <Modal title={site?"Edit SharePoint site":"Register SharePoint site"} onClose={onClose} width={560}
    footer={<SaveFooter onClose={onClose} onSave={save} loading={loading} label="Save site"/>}>
    <Field label="Display name *"><input className="field" value={form.name} onChange={e=>set("name",e.target.value)} placeholder="e.g. Trailblazers Site"/></Field>
    <Field label="Site URL *"><input className="field mono" value={form.site_url} onChange={e=>set("site_url",e.target.value)} placeholder="https://company.sharepoint.com/sites/TrailblazersHub"/></Field>
    <Field label="Site type"><div style={{display:"flex",gap:8}}>
      <button type="button" className={"choice"+((form.site_type||"internal")==="internal"?" on":"")} onClick={()=>set("site_type","internal")}>Internal<small>Company SharePoint</small></button>
      <button type="button" className={"choice"+(form.site_type==="external"?" on":"")} onClick={()=>set("site_type","external")}>External<small>Needs its own app credentials</small></button>
    </div></Field>
    {form.site_type==="external"&&<>
      <div className="grid2 form-row">
        <div><label className="lbl">Tenant ID *</label><input className="field mono" value={form.tenant_id} onChange={e=>set("tenant_id",e.target.value)} placeholder="xxxxxxxx-xxxx-…"/></div>
        <div><label className="lbl">Client ID *</label><input className="field mono" value={form.client_id} onChange={e=>set("client_id",e.target.value)} placeholder="xxxxxxxx-xxxx-…"/></div>
      </div>
      <Field label={`Client secret ${site?"(leave blank to keep existing)":"*"}`}><input className="field mono" type="password" value={form.client_secret} onChange={e=>set("client_secret",e.target.value)} placeholder={site?"••••••••••••":"Paste client secret"}/></Field>
    </>}
    <Field label="Drive ID (optional)" hint="Leave blank — Conductor will auto-resolve the Documents library on first use."><input className="field mono" value={form.drive_id} onChange={e=>set("drive_id",e.target.value)} placeholder="Auto-resolved if left blank"/></Field>
    <ErrNote>{err}</ErrNote>
  </Modal>;
}