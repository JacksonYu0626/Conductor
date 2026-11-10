// ─── workspace.jsx ───────────────────────────────────────────────────────────
// Users, Feedback, My profile.

// ─── Users ────────────────────────────────────────────────────────────────────
function UserEditModal({u,onSave,onClose}){
  const [form,setForm]=useState({name:u.name||"",role:u.role||"user",department:u.department||"",title:u.title||""});
  const [loading,setLoading]=useState(false);const [err,setErr]=useState("");
  const set=(k,v)=>setForm(f=>({...f,[k]:v}));
  const save=async()=>{if(!form.name){setErr("Name is required.");return;}setLoading(true);setErr("");
    try{const r=await api.updateUser(u.id,form);onSave(r);}catch(e){setErr(e.message);}finally{setLoading(false);}};
  return <Modal title="Edit user" sub={u.email} onClose={onClose} width={480} footer={<SaveFooter onClose={onClose} onSave={save} loading={loading} label="Save changes"/>}>
    <Field label="Full name"><input className="field" value={form.name} onChange={e=>set("name",e.target.value)}/></Field>
    <div className="grid2 form-row">
      <div><label className="lbl">Department</label><input className="field" value={form.department} onChange={e=>set("department",e.target.value)}/></div>
      <div><label className="lbl">Job title</label><input className="field" value={form.title} onChange={e=>set("title",e.target.value)}/></div>
    </div>
    <Field label="Role" hint="Admins can see and manage everyone's scripts, dashboards, sites and schedules."><Seg wide value={form.role} onChange={v=>set("role",v)} options={[["user","User"],["admin","Admin"]]}/></Field>
    <ErrNote>{err}</ErrNote>
  </Modal>;
}

function Users(){
  const {user,go,toast,confirm}=useApp();const admin=isAdminUser(user);
  const [users,setUsers]=useState(()=>peek("/users/",[]));const [loading,setLoading]=useState(true);const [search,setSearch]=useState("");const [edit,setEdit]=useState(null);
  const load=async()=>{setLoading(true);try{setUsers(await api.getUsers());}catch(e){toast(e.message,"bad");}finally{setLoading(false);}};
  useEffect(()=>{load();},[]);
  const q=search.toLowerCase();
  const me=users.find(u=>u.id===user.id);
  const others=users.filter(u=>u.id!==user.id&&(!q||u.name.toLowerCase().includes(q)||u.email.toLowerCase().includes(q)||(u.department||"").toLowerCase().includes(q)||(u.title||"").toLowerCase().includes(q)));
  const rows=[...(me&&(!q||me.name.toLowerCase().includes(q))?[me]:[]),...others];
  const remove=async u=>{if(!await confirm({title:`Remove ${u.name}?`,body:"They will no longer be able to sign in, and their active schedules will be paused. Their scripts and history are kept.",confirmLabel:"Remove user",danger:true}))return;
    try{await api.deleteUser(u.id);toast(`${u.name} removed`);load();}catch(e){toast(e.message,"bad");}};
  const Count=({u,n,page,extra})=>{
    const mine=u.id===user.id;const can=mine||admin;
    if(!can||!n)return <span className="num" style={{color:n?"var(--text2)":"var(--text3)"}}>{n||0}</span>;
    return <button className="link-btn" onClick={e=>{e.stopPropagation();go(page,mine?{}:{owner:u.id,ownerName:u.name,...extra});}} title={mine?"Open your items":`Open ${u.name}'s items`}>{n}</button>;
  };
  return <div style={{display:"flex",flexDirection:"column",gap:18}}>
    <div className="toolbar pg">
      <SearchBox value={search} onChange={setSearch} placeholder="Search people…"/>
      <span className="spacer"/>
      <span className="small muted" style={{display:"flex",alignItems:"center",gap:6}}><Icon name="info" size={14}/>Users are added by IT through Global Security.</span>
    </div>
    <div className="card pg2"><div className="tbl-wrap"><table className="tbl">
      <thead><tr><th>Name</th><th>Role</th><th className="num">Scripts</th><th className="num">Dashboards</th><th className="num">SP sites</th><th className="num">Schedules</th><th className="num">Feedback</th><th>Member since</th>{admin&&<th className="actions"><span className="sr">Actions</span></th>}</tr></thead>
      {loading&&!users.length?<SkelRows rows={6} cols={admin?9:8}/>:<tbody>
        {rows.length===0&&<tr><td colSpan={admin?9:8}><Empty title="No people found" icon="users"/></td></tr>}
        {rows.map(u=>{const mine=u.id===user.id;return <tr key={u.id} className={mine?"me":""}>
          <td><div style={{display:"flex",alignItems:"center",gap:10}}><Avatar name={u.name} size={32}/><div style={{minWidth:0}}>
            <div style={{display:"flex",alignItems:"center",gap:8,fontWeight:600,color:"var(--text)"}}>{u.name}{mine&&<span className="you">You</span>}</div>
            <div className="small muted trunc">{[u.title,u.department].filter(Boolean).join(" · ")||u.email}</div></div></div></td>
          <td><span className={"chip "+(isAdminUser(u)?"chip-run":"chip-idle")} style={{textTransform:"capitalize"}}>{u.role}</span></td>
          <td className="num"><Count u={u} n={u.script_count} page="scripts"/></td>
          <td className="num"><Count u={u} n={u.dashboard_count} page="dashboards"/></td>
          <td className="num"><Count u={u} n={u.sharepoint_site_count} page="sp_sites"/></td>
          <td className="num"><Count u={u} n={u.schedule_count} page="schedules" extra={{ownerEmail:u.email}}/></td>
          <td className="num">{u.feedback_count?<button className="link-btn" onClick={()=>go("feedback",{userId:u.id,userName:u.name})} title={mine?"Open your feedback":`Open ${u.name}'s feedback`}>{u.feedback_count}</button>:<span className="num" style={{color:"var(--text3)"}}>0</span>}</td>
          <td>{fmtDateShort(u.created_at)}</td>
          {admin&&<td className="actions"><button className="btn btn-sm" onClick={()=>setEdit(u)}>Edit</button>{!mine&&<button className="btn btn-sm btn-danger" onClick={()=>remove(u)}>Remove</button>}</td>}
        </tr>;})}
      </tbody>}
    </table></div></div>
    {!admin&&<p className="small muted" style={{margin:0}}>You can see who uses Conductor and how much they've set up. Feedback is public, so anyone can open it. Only you (and admins) can open your scripts, dashboards, sites and schedules.</p>}
    {edit&&<UserEditModal u={edit} onSave={()=>{setEdit(null);toast("User updated");load();}} onClose={()=>setEdit(null)}/>}
  </div>;
}

// ─── Feedback ─────────────────────────────────────────────────────────────────
const FB_TYPES={Bug:"warn",Feature:"star",Improvement:"bolt",Other:"feedback"};
const FB_PRIORITY=["Low","Medium","High"];
function parseFb(raw){
  if(!raw)return{text:"",rating:0,priority:"Medium"};
  const parts=raw.split("||");const r=parts.find(p=>p.startsWith("rating:"));const pr=parts.find(p=>p.startsWith("priority:"));
  return{text:parts[0],rating:r?parseInt(r.split(":")[1])||0:0,priority:pr?pr.split(":")[1]:"Medium"};
}
function Stars({value,onChange,readonly}){
  const [h,setH]=useState(0);
  return <div style={{display:"flex",gap:2,alignItems:"center"}}>{[1,2,3,4,5].map(i=>{const on=i<=(readonly?value:(h||value));
    return <button key={i} type="button" disabled={readonly} onClick={()=>onChange&&onChange(i===value?0:i)} onMouseEnter={()=>!readonly&&setH(i)} onMouseLeave={()=>!readonly&&setH(0)} aria-label={`${i} star${i>1?"s":""}`}
      style={{border:"none",background:"none",padding:readonly?0:2,cursor:readonly?"default":"pointer",color:on?"#f59e0b":"var(--border2)",display:"flex"}}>
      <svg width={readonly?14:20} height={readonly?14:20} viewBox="0 0 24 24" fill={on?"currentColor":"none"} stroke="currentColor" strokeWidth="2" strokeLinejoin="round"><path d={ICONS.star}/></svg></button>;})}
    {!readonly&&value>0&&<span className="small muted" style={{marginLeft:6}}>{["","Poor","Fair","Good","Great","Excellent"][value]}</span>}
  </div>;
}
function EditedMark({at}){
  if(!at)return null;
  return <span className="small muted" title={`Edited ${fmtDate(at)}`} style={{borderBottom:"1px dotted currentColor",cursor:"help"}}>· edited</span>;
}
// Inline editor for your own feedback: same fields as the send form
function FeedbackEditor({f,onSaved,onCancel}){
  const {toast}=useApp();const p0=parseFb(f.message);
  const [type,setType]=useState(f.type||"Bug");const [priority,setPriority]=useState(p0.priority||"Medium");const [rating,setRating]=useState(p0.rating||0);const [text,setText]=useState(p0.text||"");const [busy,setBusy]=useState(false);
  const save=async()=>{if(!text.trim()||busy)return;setBusy(true);
    try{const r=await api.editFeedback(f.id,{type,message:`${text.trim()}||rating:${rating}||priority:${priority}`});onSaved(r);toast("Feedback updated");}
    catch(e){toast(e.message,"bad");}finally{setBusy(false);}};
  return <div className="drop" style={{display:"flex",flexDirection:"column",gap:10,marginTop:4}}>
    <div style={{display:"flex",gap:6,flexWrap:"wrap",alignItems:"center"}}>
      {Object.keys(FB_TYPES).map(t=><button key={t} type="button" className={"choice"+(type===t?" on":"")} onClick={()=>setType(t)} style={{flex:"0 0 auto",minHeight:32,padding:"0 12px",display:"flex",alignItems:"center",gap:6}}><Icon name={FB_TYPES[t]} size={13}/>{t}</button>)}
      <span style={{width:6}}/><Seg value={priority} onChange={setPriority} options={FB_PRIORITY.map(x=>[x,x])} ariaLabel="Priority"/>
      <span style={{width:6}}/><Stars value={rating} onChange={setRating}/>
    </div>
    <textarea className="field" value={text} onChange={e=>setText(e.target.value)} autoFocus style={{minHeight:84}} aria-label="Details"/>
    <div style={{display:"flex",gap:8,alignItems:"center",flexWrap:"wrap"}}>
      <span className="small muted">Status stays {f.status==="In Review"?"In review":f.status} — only an admin changes it.</span><span style={{flex:1}}/>
      <button className="btn btn-sm" onClick={onCancel}>Cancel</button>
      <button className="btn btn-sm btn-primary" onClick={save} disabled={busy||!text.trim()}>{busy?<Spinner size={13} color="#fff"/>:"Save changes"}</button>
    </div>
  </div>;
}
function UpvoteBtn({n,on,onClick,small}){
  return <button type="button" onClick={onClick} aria-pressed={!!on} aria-label={on?"Remove your upvote":"Upvote"} title={on?"Remove your upvote":"Upvote"}
    className={"upvote"+(on?" on":"")+(small?" sm":"")}><Icon name="up" size={small?12:16} sw={2.4}/><span>{n||0}</span></button>;
}
function CommentThread({f,onCount}){
  const {user,toast,confirm}=useApp();const admin=isAdminUser(user);
  const [items,setItems]=useState(null);const [text,setText]=useState("");const [busy,setBusy]=useState(false);
  const [editId,setEditId]=useState(null);const [editText,setEditText]=useState("");
  const saveEdit=async c=>{const t=editText.trim();if(!t)return;
    try{const r=await api.editComment(c.id,t);setItems(p=>p.map(x=>x.id===c.id?r:x));setEditId(null);}catch(e){toast(e.message,"bad");}};
  useEffect(()=>{api.getComments(f.id).then(setItems).catch(e=>{toast(e.message,"bad");setItems([]);});},[f.id]);
  const post=async()=>{const t=text.trim();if(!t||busy)return;setBusy(true);
    try{const c=await api.addComment(f.id,t);setItems(p=>{const n=[...(p||[]),c];onCount(n.length);return n;});setText("");}
    catch(e){toast(e.message,"bad");}finally{setBusy(false);}};
  const vote=async c=>{setItems(p=>p.map(x=>x.id===c.id?{...x,voted:!x.voted,vote_count:x.vote_count+(x.voted?-1:1)}:x));
    try{const r=await api.voteComment(c.id);setItems(p=>p.map(x=>x.id===c.id?{...x,...r}:x));}catch(e){toast(e.message,"bad");}};
  const del=async c=>{if(!await confirm({title:"Delete this comment?",body:"It will be removed for everyone.",confirmLabel:"Delete",danger:true}))return;
    try{await api.deleteComment(c.id);setItems(p=>{const n=p.filter(x=>x.id!==c.id);onCount(n.length);return n;});}catch(e){toast(e.message,"bad");}};
  return <div className="thread drop">
    {items==null?<div className="small muted" style={{display:"flex",gap:8,alignItems:"center"}}><Spinner size={12}/>Loading comments…</div>
    :items.length===0?<div className="small muted">No comments yet. Start the discussion.</div>
    :items.map(c=>{const mine=c.user?.id===user.id;return <div key={c.id} style={{display:"flex",gap:10}}>
      <Avatar name={c.user?.name||"?"} size={26}/>
      <div style={{flex:1,minWidth:0}}>
        <div style={{display:"flex",alignItems:"center",gap:8,flexWrap:"wrap"}}>
          <b style={{fontSize:13}}>{c.user?.name||"Someone"}</b>{mine&&<span className="you">You</span>}
          {isAdminUser(c.user)&&<span className="chip chip-run" style={{padding:"1px 7px",fontSize:11}}>Admin</span>}
          <span className="small muted">{fmtWhen(c.created_at)}</span><EditedMark at={c.edited_at}/><span style={{flex:1}}/>
          {mine&&editId!==c.id&&<button className="link-btn" style={{fontSize:12,fontWeight:500,color:"var(--text2)"}} onClick={()=>{setEditId(c.id);setEditText(c.message);}}>Edit</button>}
          {(mine||admin)&&editId!==c.id&&<button className="link-btn" style={{fontSize:12,fontWeight:500,color:"var(--text3)"}} onClick={()=>del(c)}>Delete</button>}
        </div>
        {editId===c.id?<div className="drop" style={{marginTop:4}}>
          <textarea className="field" value={editText} onChange={e=>setEditText(e.target.value)} autoFocus aria-label="Edit comment"
            onKeyDown={e=>{if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();saveEdit(c);}if(e.key==="Escape"){e.stopPropagation();setEditId(null);}}} style={{minHeight:38,height:60}}/>
          <div style={{display:"flex",gap:8,justifyContent:"flex-end",marginTop:6}}><button className="btn btn-sm" onClick={()=>setEditId(null)}>Cancel</button><button className="btn btn-sm btn-primary" onClick={()=>saveEdit(c)} disabled={!editText.trim()}>Save</button></div>
        </div>:<>
        <p style={{margin:"3px 0 6px",fontSize:13.5,lineHeight:1.55,whiteSpace:"pre-wrap",wordBreak:"break-word"}}>{c.message}</p>
        <UpvoteBtn small n={c.vote_count} on={c.voted} onClick={()=>vote(c)}/></>}
      </div>
    </div>;})}
    <div style={{display:"flex",gap:8,alignItems:"flex-start"}}>
      <Avatar name={user.name} size={26}/>
      <textarea className="field" rows={1} value={text} onChange={e=>setText(e.target.value)} placeholder="Write a comment…  (Enter to post, Shift+Enter for a new line)"
        onKeyDown={e=>{if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();post();}}} style={{flex:1,minHeight:38,height:38,padding:"8px 12px",resize:"vertical"}}/>
      <button className="btn btn-primary" onClick={post} disabled={!text.trim()||busy}>{busy?<Spinner size={14} color="#fff"/>:"Comment"}</button>
    </div>
  </div>;
}
function Feedback({params}){
  const {user,toast,confirm}=useApp();const admin=isAdminUser(user);
  const [items,setItems]=useState(()=>peek("/feedback/",[]));const [loading,setLoading]=useState(true);
  const [msg,setMsg]=useState("");const [type,setType]=useState("Bug");const [priority,setPriority]=useState("Medium");const [rating,setRating]=useState(0);const [busy,setBusy]=useState(false);
  const [fType,setFType]=useState("All");const [fStatus,setFStatus]=useState("All");const [sort,setSort]=useState("top");
  const [person,setPerson]=useState(params?.userId?{id:params.userId,name:params.userName}:null);
  const [openThread,setOpenThread]=useState(null);const [editing,setEditing]=useState(null);
  useEffect(()=>{if(params?.userId)setPerson({id:params.userId,name:params.userName});},[params]);
  const load=async()=>{setLoading(true);try{setItems(await api.getFeedback());}catch(e){toast(e.message,"bad");}finally{setLoading(false);}};
  useEffect(()=>{load();},[]);
  const submit=async()=>{if(!msg.trim())return;setBusy(true);
    try{await api.createFeedback({type,message:`${msg}||rating:${rating}||priority:${priority}`},user?.id);setMsg("");setRating(0);setPriority("Medium");toast("Thanks — feedback posted");load();}
    catch(e){toast(e.message,"bad");}finally{setBusy(false);}};
  const counts={Open:0,"In Review":0,Resolved:0};items.forEach(f=>{if(counts[f.status]!=null)counts[f.status]++;});
  const total=items.length;
  const rated=items.map(f=>parseFb(f.message).rating).filter(r=>r>0);const avg=rated.length?(rated.reduce((a,b)=>a+b,0)/rated.length).toFixed(1):null;
  const filtered=items.filter(f=>(fType==="All"||f.type===fType)&&(fStatus==="All"||f.status===fStatus)&&(!person||f.user?.id===person.id))
    .sort((a,b)=>sort==="top"?((b.vote_count||0)-(a.vote_count||0))||(toDate(b.created_at)-toDate(a.created_at)):toDate(b.created_at)-toDate(a.created_at));
  const patch=(id,ch)=>setItems(p=>p.map(x=>x.id===id?{...x,...ch}:x));
  const setStatus=async(f,st)=>{try{await api.updateFeedback(f.id,st);patch(f.id,{status:st});}catch(e){toast(e.message,"bad");}};
  const vote=async f=>{patch(f.id,{voted:!f.voted,vote_count:(f.vote_count||0)+(f.voted?-1:1)});
    try{const r=await api.voteFeedback(f.id);patch(f.id,r);}catch(e){patch(f.id,{voted:f.voted,vote_count:f.vote_count});toast(e.message,"bad");}};
  const del=async f=>{const mine=f.user?.id===user.id;
    if(!await confirm({title:mine?"Delete your feedback?":"Delete this feedback?",body:"It will be removed for everyone, along with its comments and upvotes.",confirmLabel:"Delete",danger:true}))return;
    try{await api.deleteFeedback(f.id);toast("Feedback deleted");setItems(p=>p.filter(x=>x.id!==f.id));}catch(e){toast(e.message,"bad");}};
  const bar=[["Open","var(--bad)"],["In Review","var(--accent)"],["Resolved","var(--ok)"]];
  return <div style={{display:"flex",flexDirection:"column",gap:18}}>
    <div className="card card-pad pg">
      <div style={{display:"flex",alignItems:"center",gap:24,flexWrap:"wrap",marginBottom:12}}>
        <div><div className="display" style={{fontSize:28,fontWeight:800,lineHeight:1}}>{total}</div><div className="small muted">items</div></div>
        {bar.map(([k,c])=><button key={k} type="button" onClick={()=>setFStatus(fStatus===k?"All":k)} style={{border:"none",background:"none",padding:0,cursor:"pointer",textAlign:"left",color:"var(--text)"}}><div style={{display:"flex",alignItems:"center",gap:6,fontWeight:700,fontSize:18}}><span className="dot8" style={{background:c}}/>{counts[k]}</div><div className="small muted">{k==="In Review"?"In review":k}</div></button>)}
        <span style={{flex:1}}/>
        {avg&&<div style={{textAlign:"right"}}><div style={{display:"flex",alignItems:"center",gap:6,fontWeight:700,fontSize:18}}><Stars value={Math.round(avg)} readonly/>{avg}</div><div className="small muted">average rating</div></div>}
      </div>
      <div style={{display:"flex",height:8,borderRadius:4,overflow:"hidden",background:"var(--surface2)",gap:2}}>
        {bar.map(([k,c])=>counts[k]?<div key={k} className="bar" style={{flex:counts[k],background:c,transformOrigin:"left",animationName:"fadeIn"}} title={`${k}: ${counts[k]}`}/>:null)}
      </div>
    </div>
    <div className="cols pg2" style={{gridTemplateColumns:"minmax(0,1fr) minmax(0,2fr)"}}>
      <div className="card card-pad" style={{position:"sticky",top:96}}>
        <div className="card-title" style={{marginBottom:12}}>Send feedback</div>
        <div className="note note-info" style={{marginBottom:14}}><Icon name="eye" size={16}/><div><b>Visible to everyone.</b> Anyone who uses Conductor can read, upvote and comment.</div></div>
        <Field label="Type"><div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:6}}>{Object.keys(FB_TYPES).map(t=><button key={t} type="button" className={"choice"+(type===t?" on":"")} onClick={()=>setType(t)} style={{display:"flex",alignItems:"center",gap:6,justifyContent:"center"}}><Icon name={FB_TYPES[t]} size={14}/>{t}</button>)}</div></Field>
        <Field label="Priority"><Seg wide value={priority} onChange={setPriority} options={FB_PRIORITY.map(p=>[p,p])}/></Field>
        <Field label="How's Conductor working for you?"><Stars value={rating} onChange={setRating}/></Field>
        <Field label="Details"><textarea className="field" value={msg} onChange={e=>setMsg(e.target.value)} placeholder="Describe the issue or idea…" style={{minHeight:110}}/></Field>
        <button className="btn btn-primary btn-block" onClick={submit} disabled={busy||!msg.trim()}>{busy?<><Spinner size={14} color="#fff"/>Sending…</>:"Send feedback"}</button>
      </div>
      <div className="card">
        <div className="card-head">
          <Seg value={fType} onChange={setFType} options={[["All","All types"],...Object.keys(FB_TYPES).map(t=>[t,t])]} ariaLabel="Type filter"/>
          <div style={{display:"flex",gap:8,flexWrap:"wrap",alignItems:"center"}}>
            {person&&<span className="chip chip-run" style={{height:32,padding:"0 6px 0 12px"}}>From: {person.name}<button className="btn btn-quiet btn-sm btn-icon" style={{height:24,width:24,color:"inherit"}} onClick={()=>setPerson(null)} aria-label="Show everyone's feedback"><Icon name="x" size={13}/></button></span>}
            <select className="field" style={{width:"auto"}} value={sort} onChange={e=>setSort(e.target.value)} aria-label="Sort"><option value="top">Most upvoted</option><option value="new">Newest</option></select>
            <select className="field" style={{width:"auto"}} value={fStatus} onChange={e=>setFStatus(e.target.value)} aria-label="Status filter"><option value="All">All statuses</option><option value="Open">Open</option><option value="In Review">In review</option><option value="Resolved">Resolved</option></select>
          </div>
        </div>
        {loading&&!items.length?<div className="card-pad"><Skel/><Skel w="50%" style={{marginTop:10}}/></div>
        :filtered.length===0?<Empty title="No feedback here" sub={person?`${person.name} hasn't posted anything that matches these filters`:"Be the first to share an idea or report a bug"} icon="feedback"/>
        :filtered.map(f=>{const p=parseFb(f.message);const mine=f.user?.id===user.id;const open=openThread===f.id;const n=f.comment_count||0;
          return <div key={f.id} className="list-row" style={{alignItems:"flex-start",gap:14}}>
            <UpvoteBtn n={f.vote_count} on={f.voted} onClick={()=>vote(f)}/>
            <div style={{flex:1,minWidth:0}}>
              <div style={{display:"flex",alignItems:"center",gap:8,flexWrap:"wrap",marginBottom:4}}>
                <Avatar name={f.user?.name||"?"} size={26}/>
                <b>{f.user?.name||"Anonymous"}</b>{mine&&<span className="you">You</span>}
                <span className="tag"><Icon name={FB_TYPES[f.type]||"feedback"} size={12}/>{f.type}</span>
                <span className={"chip "+(p.priority==="High"?"chip-bad":p.priority==="Low"?"chip-idle":"chip-warn")}>{p.priority}</span>
                {p.rating>0&&<Stars value={p.rating} readonly/>}
                <span style={{marginLeft:"auto"}}><StatusChip status={f.status} label={f.status==="In Review"?"In review":f.status}/></span>
              </div>
              {editing===f.id?<FeedbackEditor f={f} onCancel={()=>setEditing(null)} onSaved={r=>{patch(f.id,r);setEditing(null);}}/>:<>
              <p style={{margin:"0 0 8px",fontSize:13.5,lineHeight:1.6,whiteSpace:"pre-wrap",wordBreak:"break-word"}}>{p.text}</p>
              <div style={{display:"flex",alignItems:"center",gap:14,flexWrap:"wrap"}}>
                <span className="small muted" style={{display:"inline-flex",gap:6}}>{fmtDateShort(f.created_at)}<EditedMark at={f.edited_at}/></span>
                <button className="link-btn" style={{fontSize:13,display:"inline-flex",alignItems:"center",gap:6}} onClick={()=>setOpenThread(open?null:f.id)} aria-expanded={open}>
                  <Icon name="msg" size={14}/>{n} comment{n===1?"":"s"}{open?" · Hide":""}</button>
                <span style={{flex:1}}/>
                {admin&&<Seg value={f.status} onChange={st=>setStatus(f,st)} options={[["Open","Open"],["In Review","In review"],["Resolved","Resolved"]]} ariaLabel="Set status"/>}
                {mine&&<button className="btn btn-sm btn-quiet" onClick={()=>setEditing(f.id)}><Icon name="edit" size={13}/>Edit</button>}
                {(mine||admin)&&<button className="btn btn-sm btn-quiet" style={{color:"var(--badText)"}} onClick={()=>del(f)}><Icon name="trash" size={13}/>Delete</button>}
              </div></>}
              {open&&<CommentThread f={f} onCount={c=>patch(f.id,{comment_count:c})}/>}
            </div>
          </div>;})}
      </div>
    </div>
  </div>;
}

// ─── My profile ───────────────────────────────────────────────────────────────
function Profile(){
  const {user,themePref,setThemePref,logout,go}=useApp();const admin=isAdminUser(user);
  const [week,setWeek]=useState(()=>peek("/analytics/runs?period=week&job_type=all",null));const [me,setMe]=useState(()=>peek("/users/",[]).find(u=>u.id===user.id)||null);
  useEffect(()=>{api.analytics("week","all").then(setWeek).catch(()=>{});api.getUsers().then(us=>setMe(us.find(u=>u.id===user.id))).catch(()=>{});},[]);
  const items=[["Scripts",me?.script_count,"scripts"],["Dashboards",me?.dashboard_count,"dashboards"],["SharePoint sites",me?.sharepoint_site_count,"sp_sites"],["Schedules",me?.schedule_count,"schedules"]];
  return <div style={{display:"flex",flexDirection:"column",gap:20}}>
    <div className="card card-pad pg" style={{display:"flex",alignItems:"center",gap:18,flexWrap:"wrap"}}>
      <span className="pop" style={{display:"flex"}}><Avatar name={user.name} size={64}/></span>
      <div style={{flex:1,minWidth:200}}>
        <div className="display" style={{fontSize:22,fontWeight:800}}>{user.name}</div>
        <div className="muted">{[user.title,user.department].filter(Boolean).join(" · ")||"—"}</div>
        <div style={{display:"flex",gap:8,marginTop:8,flexWrap:"wrap"}}><span className={"chip "+(admin?"chip-run":"chip-idle")} style={{textTransform:"capitalize"}}>{user.role}</span><span className="tag mono">{user.email}</span></div>
      </div>
      <button className="btn" onClick={logout}><Icon name="logout" size={15}/>Sign out</button>
    </div>
    <div className="cols-even pg2" style={{alignItems:"stretch"}}>
      <div className="card">
        <div className="card-head"><div><div className="card-title">Runs this week</div><div className="card-sub">{admin?"All teams (you're an admin)":"Your scripts, dashboards and uploads"}</div></div></div>
        <div className="card-pad">{week?<><MiniBars values={week.total} labels={week.labels.map(l=>l.split(" ")[0])}/><div className="small muted" style={{marginTop:6}}>{week.summary.total} runs · {week.summary.success_rate}% successful</div></>:<Skel h={90}/>}</div>
      </div>
      <div className="card">
        <div className="card-head"><div className="card-title">What you've set up</div></div>
        {items.map(([l,n,pg])=><div key={l} className="list-row click" onClick={()=>go(pg)}><span style={{flex:1}}>{l}</span><b>{n??"—"}</b><Icon name="chevR" size={15} style={{color:"var(--text3)"}}/></div>)}
      </div>
    </div>
    <div className="card pg3">
      <div className="card-head"><div><div className="card-title">Appearance</div><div className="card-sub">Saved in this browser</div></div></div>
      <div className="card-pad" style={{display:"flex",alignItems:"center",gap:16,flexWrap:"wrap"}}>
        <span style={{flex:1,minWidth:200}}>Default theme</span>
        <Seg value={themePref} onChange={setThemePref} options={[["light",<><Icon name="sun" size={14}/>Light</>],["dark",<><Icon name="moon" size={14}/>Dark</>],["system","Match Windows"]]} ariaLabel="Default theme"/>
      </div>
    </div>
    <div className="card card-pad pg3">
      <div className="card-title" style={{marginBottom:6}}>Your account</div>
      <p className="small muted" style={{margin:0,lineHeight:1.6}}>You sign in with your MPM Windows account through Global Security. Your name, department and title come from there — ask IT if something is out of date.{user.created_at?` Member since ${fmtDateShort(user.created_at)}.`:""}</p>
    </div>
  </div>;
}