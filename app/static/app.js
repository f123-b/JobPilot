const $ = (id) => document.getElementById(id);
let currentTask = null;
let traceSocket = null;
let currentResumeSourceId = null;

async function api(path, options={}) {
  const res = await fetch(path, {headers:{'Content-Type':'application/json'}, ...options});
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || JSON.stringify(data));
  return data;
}

function pretty(x){ return JSON.stringify(x,null,2); }
function escapeHtml(s){return String(s).replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));}

function requestPayload(autoExecute=false){
  return {
    objective:$('objective').value,
    task_type:$('taskType').value,
    user_id:$('userId')?.value||'default',
    job_url:$('jobUrl').value||null,
    resume_text:$('resume').value||null,
    resume_source_id:currentResumeSourceId,
    auto_execute:autoExecute
  };
}

function resetAgentBar(){
  document.querySelectorAll('#workflowBar [data-agent]').forEach(el=>el.classList.remove('active-agent','done-agent','planned-agent'));
}
function renderPlan(plan){
  resetAgentBar();
  (plan?.steps||[]).map(x=>x.agent).forEach(agent=>document.querySelector(`#workflowBar [data-agent="${agent}"]`)?.classList.add('planned-agent'));
}
function setActiveAgent(agent){
  if(!agent)return;
  const el=document.querySelector(`#workflowBar [data-agent="${agent}"]`);
  if(el){
    document.querySelectorAll('#workflowBar [data-agent].active-agent').forEach(x=>{x.classList.remove('active-agent');x.classList.add('done-agent')});
    el.classList.remove('planned-agent'); el.classList.add('active-agent');
  }
}

document.querySelectorAll('.tab').forEach(btn => btn.onclick = () => {
  document.querySelectorAll('.tab,.panel').forEach(x=>x.classList.remove('active'));
  btn.classList.add('active'); $(btn.dataset.tab).classList.add('active');
  if (btn.dataset.tab === 'jobs') loadJobs();
  if (btn.dataset.tab === 'ops') loadMetrics();
});

(async()=>{try{const h=await api('/api/health');$('health').textContent=h.browser_agent_configured?`V${h.version} · Multi-Agent ready`:`V${h.version} · Planner demo`;}catch{$('health').textContent='Offline'}})();

$('parseBtn').onclick=async()=>{ $('matchOut').textContent='解析中…'; try{$('matchOut').textContent=pretty(await api('/api/jd/parse',{method:'POST',body:JSON.stringify({text:$('jd').value})}));}catch(e){$('matchOut').textContent=e.message}};
$('matchBtn').onclick=async()=>{ $('matchOut').textContent='计算 Skill + Embedding 匹配…'; try{$('matchOut').textContent=pretty(await api('/api/match',{method:'POST',body:JSON.stringify({resume_text:$('resume').value,jd_text:$('jd').value})}));}catch(e){$('matchOut').textContent=e.message}};

$('planBtn').onclick=async()=>{
  $('agentOut').textContent='Planner 生成计划…'; resetAgentBar();
  try{const plan=await api('/api/plan',{method:'POST',body:JSON.stringify(requestPayload(false))});renderPlan(plan);$('agentOut').textContent=pretty(plan);}catch(e){$('agentOut').textContent=e.message}
};
$('runBtn').onclick=async()=>{
  $('agentOut').textContent='创建任务…'; $('traceList').innerHTML='<div class="muted">等待 Planner 启动…</div>'; $('approvalBox').classList.add('hidden'); resetAgentBar();
  if(traceSocket)traceSocket.close();
  try{const data=await api('/api/tasks',{method:'POST',body:JSON.stringify(requestPayload(false))});currentTask=data.id;$('agentOut').textContent=pretty(data);connectTrace(currentTask);if(data.status==='waiting_approval')$('approvalBox').classList.remove('hidden');}catch(e){$('agentOut').textContent=e.message}
};
$('approveBtn').onclick=async()=>{
  if(!currentTask)return; $('approvalBox').classList.add('hidden');
  try{$('agentOut').textContent=pretty(await api(`/api/tasks/${currentTask}/approve`,{method:'POST',body:JSON.stringify({approved:true,note:'Approved from JobPilot UI'})}));}catch(e){$('agentOut').textContent=e.message}
};

function connectTrace(taskId){
  const protocol=location.protocol==='https:'?'wss':'ws';
  traceSocket=new WebSocket(`${protocol}://${location.host}/ws/tasks/${taskId}`);
  traceSocket.onmessage=(ev)=>{
    const msg=JSON.parse(ev.data);
    if(msg.type==='trace')appendTrace(msg.data);
    if(msg.type==='status'){if(msg.data.plan)renderPlan(msg.data.plan);setActiveAgent(msg.data.current_agent);$('agentOut').textContent=pretty(msg.data);}
    if(msg.type==='done'){document.querySelectorAll('#workflowBar [data-agent].active-agent').forEach(x=>{x.classList.remove('active-agent');x.classList.add('done-agent')});$('agentOut').textContent=pretty(msg.data);if(msg.data.task_type==='job_search')loadJobs();}
  };
}
function appendTrace(trace){
  if($('traceList').querySelector('.muted'))$('traceList').innerHTML='';
  const item=document.createElement('div');item.className='trace';
  item.innerHTML=`<div class="trace-head"><strong>${escapeHtml(trace.event_type)}</strong><span>${escapeHtml((trace.created_at||'').slice(11,19))}</span></div><pre>${escapeHtml(pretty(trace.detail||{}))}</pre>`;
  $('traceList').appendChild(item);$('traceList').scrollTop=$('traceList').scrollHeight;
}
async function loadJobs(){
  try{const jobs=await api('/api/jobs');$('jobsList').innerHTML=jobs.length?jobs.map(j=>`<div class="card"><div class="card-top"><h3>${escapeHtml(j.title)}</h3><span class="score">${j.match_score??'-'}</span></div><div class="muted">${escapeHtml(j.company||'未知公司')} · ${escapeHtml(j.location||'未知地点')}</div><div class="muted">${escapeHtml(j.source||'unknown source')}</div>${j.url?`<a href="${escapeHtml(j.url)}" target="_blank" rel="noreferrer">打开岗位</a>`:''}</div>`).join(''):'暂无岗位记录';}catch(e){$('jobsList').textContent=e.message}
}
$('refreshJobs').onclick=loadJobs;

$('indexResumeBtn').onclick=async()=>{
  const file=$('resumeFile').files[0];if(!file){$('memoryOut').textContent='请选择简历文件';return}
  $('memoryOut').textContent='解析、切块并生成向量索引…';
  try{const userId=encodeURIComponent($('userId').value||'default');const filename=encodeURIComponent(file.name);const res=await fetch(`/api/resume/index?user_id=${userId}&filename=${filename}`,{method:'POST',body:await file.arrayBuffer()});const data=await res.json();if(!res.ok)throw new Error(data.detail||JSON.stringify(data));currentResumeSourceId=data.source_id;$('memoryOut').textContent=pretty(data);}catch(e){$('memoryOut').textContent=e.message}
};
$('searchResumeBtn').onclick=async()=>{try{$('memoryOut').textContent=pretty(await api('/api/resume/search',{method:'POST',body:JSON.stringify({user_id:$('userId').value||'default',source_id:currentResumeSourceId,query:$('ragQuery').value,top_k:5})}));}catch(e){$('memoryOut').textContent=e.message}};
$('saveMemoryBtn').onclick=async()=>{try{const uid=encodeURIComponent($('userId').value||'default');$('memoryOut').textContent=pretty(await api(`/api/memory/users/${uid}/target_location`,{method:'PUT',body:JSON.stringify({value:$('memoryLocation').value})}));}catch(e){$('memoryOut').textContent=e.message}};
$('loadMemoryBtn').onclick=async()=>{try{const uid=encodeURIComponent($('userId').value||'default');$('memoryOut').textContent=pretty(await api(`/api/memory/users/${uid}`));}catch(e){$('memoryOut').textContent=e.message}};

async function loadMetrics(){try{const [metrics,queue]=await Promise.all([api('/api/metrics/summary'),api('/api/queue')]);$('metricsOut').textContent=pretty({metrics,queue});}catch(e){$('metricsOut').textContent=e.message}}
$('refreshMetrics').onclick=loadMetrics;
$('runBenchmark').onclick=async()=>{ $('benchmarkOut').textContent='运行离线 Agent Benchmark…'; try{const result=await api('/api/benchmarks/run',{method:'POST',body:'{}'});$('benchmarkOut').textContent=pretty(result);loadMetrics();}catch(e){$('benchmarkOut').textContent=e.message}};
