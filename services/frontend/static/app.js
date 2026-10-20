'use strict';
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const state = {patients:[], patient:null, metadata:null, selected:'', busy:false, controller:null, json:null, filename:'response.json', selection:0};
const statusNames = {SCREENING_BARRIER:'Screening barrier', NEEDS_MORE_INFORMATION:'More information needed', POTENTIAL_MATCH_FOR_REVIEW:'Potential match · review required'};
function setControls() {
  const ready = Boolean(state.patient) && !state.busy;
  ['question','topK','runBtn','retrieveBtn','patientJsonBtn'].forEach(id => $(id).disabled = !ready);
  document.querySelectorAll('[data-question]').forEach(button => button.disabled = !ready);
  $('patientSelect').disabled = state.busy || !state.patients.length;
  $('patientSearch').disabled = state.busy || !state.patients.length;
  $('metadataBtn').disabled = !state.metadata;
}
async function api(path, options={}) {
  const response = await fetch(path, {...options, headers:{'Content-Type':'application/json', ...options.headers}});
  let body;
  try { body = await response.json(); } catch { throw new Error(`Backend returned an unreadable response (HTTP ${response.status}).`); }
  if (!response.ok) { const error = new Error(typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail || body.errors || body)); error.body = body; error.status = response.status; throw error; }
  return body;
}
function jsonDialog(title, data, filename, note='Actual backend data. All patient records in this demonstration are synthetic.') {
  state.json=data; state.filename=filename; $('dialogTitle').textContent=title; $('dialogNote').textContent=note;
  $('jsonPreview').textContent=JSON.stringify(data,null,2); $('dataDialog').showModal();
}
function clearResults() { $('results').hidden=true; $('results').innerHTML=''; $('emptyState').hidden=false; $('error').textContent=''; }
function patientOptions() {
  const search = $('patientSearch').value.trim().toLowerCase();
  const matches = state.patients.filter(p=>p.patient_id.toLowerCase().includes(search));
  $('patientSelect').innerHTML=matches.map(p=>`<option value="${esc(p.patient_id)}">${esc(p.patient_id.slice(0,8))}… · ${esc(p.age_years_at_reference ?? '?')} years · ${esc(p.gender)}</option>`).join('') || '<option value="">No matching patients</option>';
  $('patientCount').textContent=`${matches.length} of ${state.patients.length} patients`;
  if (matches.some(p=>p.patient_id===state.selected)) $('patientSelect').value=state.selected;
  return $('patientSelect').value;
}
async function selectPatient(id) {
  const version=++state.selection; state.selected=id; state.patient=null; clearResults(); setControls();
  $('patientCard').textContent=id?'Loading patient record…':'No patient matches your search.';
  $('contextPill').textContent='No patient selected';
  if (!id) return;
  try {
    const p=await api(`/patients/${encodeURIComponent(id)}`);
    if (version!==state.selection) return;
    state.patient=p;
    const d=p.demographics;
    $('patientCard').innerHTML=`<div class="patient-heading"><div class="patient-avatar">S</div><div><h3>Synthetic patient</h3><p>${esc(d.age_years_at_reference)} years · ${esc(d.gender)}</p></div></div><code class="small-code">${esc(p.patient_id)}</code><div class="panel-note"><span class="mini-label">Reference date</span><strong>${esc(p.reference_date)}</strong><p>Historical record; this is not a current enrollment assessment.</p></div>${d.deceased_date?`<p class="warning-list">Source death date: ${esc(d.deceased_date)}. Review relative to the reference date.</p>`:''}<div class="record-label">AVAILABLE SOURCE RECORDS</div>${[['Conditions',p.conditions?.length],['Observations',p.observations?.length],['Medication requests',p.medications?.requests?.length],['Procedures',p.procedures?.length]].map(([name,count])=>`<div class="record-count"><span>${name}</span><strong>${count ?? 0}</strong></div>`).join('')}<p class="source-tiny">A record count is not evidence that a trial criterion is met. Use the linked facts in each assessment.</p>`;
    $('contextPill').textContent=`Patient ${id.slice(0,8)}… attached`;
  } catch(error) { if(version===state.selection){$('patientCard').textContent='Patient could not be loaded.'; $('error').textContent=error.message;} }
  if(version===state.selection) setControls();
}
async function connect() {
  $('reconnect').hidden=true; $('error').textContent=''; $('connection').textContent='Connecting…';
  try {
    const [health,list,metadata]=await Promise.all([api('/health'),api('/patients'),api('/metadata')]);
    state.patients=list.patients; state.metadata=metadata;
    $('connection').textContent=`${health.mode.toUpperCase()} · connected`;
    $('connection').className=`demo-dot mode-${health.mode}`;
    $('modeBanner').textContent=health.mode==='live'?'Live mode: real retrieval and configured model calls. Synthetic patients and historical trial snapshots; review all results.':'Offline mode: real BM25 retrieval and deterministic rules. No LLM is called; unsupported criteria remain UNKNOWN.';
    const first=patientOptions(); await selectPatient(first);
  } catch(error) { $('connection').textContent='Backend unavailable'; $('error').textContent=`Cannot connect: ${error.message}`; $('reconnect').hidden=false; setControls(); }
}
function warnings(items, error=false) {
  return items?.length?`<div class="warning-list ${error?'error-list':''}"><strong>${error?'Run errors':'Scope & warnings'}</strong>${items.map(x=>`<p>${esc(typeof x==='string'?x:`${x.code}: ${x.message}`)}</p>`).join('')}</div>`:'';
}
function tone(a) { return a.decision==='UNKNOWN'?'warn':((a.criterion_type==='exclusion')===(a.decision==='MET')?'bad':'ok'); }
function evidence(ids, ledger, title) {
  if (!ids?.length) return `<p class="small muted">${title}: none cited.</p>`;
  return `<details class="compact-details"><summary>${title} · ${ids.length} fact(s)</summary>${ids.map(id=>`<div class="evidence"><strong>${esc(id)}</strong><pre>${esc(JSON.stringify(ledger[id] || {warning:'Source fact missing from response'},null,2))}</pre></div>`).join('')}</details>`;
}
function sourceLink(url) {
  try { const parsed=new URL(url); if(parsed.protocol==='https:' && parsed.hostname==='clinicaltrials.gov') return `<a class="source-link" href="${esc(parsed.href)}" target="_blank" rel="noopener">ClinicalTrials.gov source ↗</a>`; } catch {}
  return '';
}
function renderScreen(data) {
  $('results').innerHTML=`<div class="result-heading"><div><h2>Pre-screening response</h2><div class="result-caption">${esc(data.mode.toUpperCase())} · ${esc(data.result_status)} · Reference ${esc(data.patient_reference_date)}</div></div><button class="quiet" id="responseJson">Download / view JSON ↗</button></div><p class="question-echo">Patient ${esc(data.patient_id)} · Run ${esc(data.run_id)}<br>Your question: ${esc(data.question)}</p>${warnings(data.errors,true)}<div class="answer-summary"><p class="question-response">${esc(data.answer)}</p></div>${warnings(data.warnings)}${data.candidate_trials.length?'':'<div class="empty-state"><h3>No candidate trials returned</h3><p>This does not establish ineligibility for all trials.</p></div>'}${data.candidate_trials.map((t,index)=>`<article class="trial-card"><div class="trial-top"><div class="trial-id">${esc(t.trial_id)} · ${esc(t.recruitment_status)}</div><div class="trial-title-row"><h3>${esc(t.brief_title || t.trial_id)}</h3><span class="status ${t.screening_status==='SCREENING_BARRIER'?'bad':t.screening_status==='NEEDS_MORE_INFORMATION'?'warn':'ok'}">${esc(statusNames[t.screening_status] || t.screening_status)}</span></div><p>Snapshot: ${esc(t.trial_snapshot_date)} · ${sourceLink(t.source_url)}</p><p class="question-response">${esc(t.question_response)}</p><div class="trial-stats"><span><strong>${esc(t.match_score ?? '—')} / 100</strong>criterion satisfaction</span><span><strong>${t.assessment_coverage.known}</strong>known</span><span><strong>${t.assessment_coverage.unknown}</strong>unknown</span><span><strong>${t.assessment_coverage.screening_barriers}</strong>barriers</span></div><p class="small">Not an enrollment probability. A high score does not override a screening barrier.</p>${warnings(t.warnings)}</div><details ${index===0?'open':''}><summary>Criteria & evidence · ${t.criteria_assessments.length}</summary><div class="criteria">${t.criteria_assessments.map(a=>`<div class="criterion"><div class="criterion-head"><span><span class="criterion-type">${esc(a.criterion_type.toUpperCase())}</span>${esc(a.criterion_text)}</span><span class="status ${tone(a)}">${esc(a.decision)}${a.criterion_type==='exclusion'&&a.decision==='MET'?' · exclusion triggered':''}</span></div><p>${esc(a.reason)}</p><p class="small-code">${esc(a.criterion_id)} · method: ${esc(a.method)}</p>${warnings(a.validation_warnings)}${evidence(a.evidence_fact_ids,t.evidence,'Supporting evidence')}${evidence(a.context_fact_ids,t.evidence,'Context considered (not proof of the decision)')}${a.missing_information.length?`<p><strong>Needed:</strong> ${a.missing_information.map(esc).join('; ')}</p>`:''}</div>`).join('')}</div></details><details><summary>Missing information & screening concerns</summary><div class="criteria">${[...t.missing_information,...t.screening_concerns].map(x=>`<p>${esc(x)}</p>`).join('') || '<p>None listed by the backend.</p>'}</div></details><details><summary>Retrieval metadata</summary><div class="criteria"><pre>${esc(JSON.stringify(t.retrieval,null,2))}</pre></div></details></article>`).join('')}<div class="result-end">Inclusion MET is favorable. Exclusion MET is a barrier. UNKNOWN must not be interpreted as absence.<br>All results require review. Data and model failures are not patient ineligibility.</div>`;
  $('responseJson').addEventListener('click',()=>jsonDialog('Actual screening response',data,`screen-${data.run_id}.json`));
}
function renderRetrieval(data) {
  $('results').innerHTML=`<div class="result-heading"><div><h2>Query → retrieved context</h2><p class="result-caption">LOCAL VECTOR BASELINE · Chroma cosine retrieval</p></div><button id="responseJson" class="quiet">Download / view JSON ↗</button></div><div class="answer-summary"><p>${esc(data.note)}</p><p class="small">${data.vector_count} stored criterion fragments · ${esc(data.embedding_model)}</p></div><p class="question-echo">Patient ${esc(data.patient_id)} · Question: ${esc(data.question)}</p><details><summary>Actual retrieval query and data hashes</summary><pre>${esc(JSON.stringify({retrieval_query:data.retrieval_query,source_hashes:data.source_hashes,collection:data.collection},null,2))}</pre></details>${data.chunks.map((c,i)=>`<article class="chunk"><div class="trial-id">${i+1} · ${esc(c.trial_id)} · ${esc(c.criterion_type)}</div><h3>${esc(c.criterion_id)}</h3><p>${esc(c.text)}</p><div class="small muted">Cosine distance: ${Number(c.distance).toFixed(4)} · Snapshot ${esc(c.snapshot_date)}</div><code class="small-code">${esc(c.chunk_id)}</code></article>`).join('')}<p class="small muted">Lower distance indicates closer vectors. This retrieves context only; it does not judge eligibility. The screening button separately calls the team's BM25/rules or live Gemini workflow.</p>`;
  $('responseJson').addEventListener('click',()=>jsonDialog('Actual vector retrieval result',data,'retrieved-context.json'));
}
async function run(kind) {
  if(state.busy || !state.patient) return;
  const question=$('question').value.trim();
  if(!question){$('error').textContent='Enter a screening question.'; return;}
  if (!/trial|diabet|t2d|screen|eligib|criteri|hba1c|glucose|bmi|exclu|missing|evidence|information|age|medication|risk/i.test(question)) {
    clearResults(); $('error').textContent='Please ask about clinical trial screening. This is not a general chat interface.'; return;
  }
  clearResults(); $('emptyState').hidden=true; state.busy=true; setControls();
  const controller=new AbortController(); state.controller=controller;
  const started=Date.now(); $('progress').hidden=false;
  const update=()=>{$('progressText').textContent=`${kind==='screen'?'Screening':'Retrieving context'} · ${Math.floor((Date.now()-started)/1000)}s · waiting for actual backend response`;}; update();
  const timer=setInterval(update,1000), timeout=setTimeout(()=>controller.abort('timeout'),300000);
  try {
    const data=await api(`/${kind}`,{method:'POST',body:JSON.stringify({patient_id:state.patient.patient_id,question,top_k:Number($('topK').value)}),signal:controller.signal});
    if(kind==='screen') renderScreen(data); else renderRetrieval(data);
    $('results').hidden=false;
  } catch(error) {
    $('error').textContent=controller.signal.aborted?(controller.signal.reason==='timeout'?'Request timed out after five minutes. Check backend logs before retrying.':'Request cancelled. The backend may still be completing its work.'):`Request failed${error.status?` (HTTP ${error.status})`:''}: ${error.message}`;
    if(error.body?.result_status==='ERROR') { renderScreen(error.body); $('results').hidden=false; } else $('emptyState').hidden=false;
  } finally {clearInterval(timer); clearTimeout(timeout); state.busy=false; state.controller=null; $('progress').hidden=true; setControls();}
}
$('queryForm').addEventListener('submit',event=>{event.preventDefault();run('screen');});
$('retrieveBtn').addEventListener('click',()=>run('retrieve'));
$('cancelBtn').addEventListener('click',()=>state.controller?.abort('user'));
$('patientSearch').addEventListener('input',()=>{const id=patientOptions();if(id!==state.selected)selectPatient(id);});
$('patientSelect').addEventListener('change',event=>selectPatient(event.target.value));
document.querySelectorAll('[data-question]').forEach(button=>button.addEventListener('click',()=>{$('question').value=button.dataset.question;}));
$('patientJsonBtn').addEventListener('click',()=>jsonDialog('Normalized patient record',state.patient,`patient-${state.patient.patient_id}.json`));
$('metadataBtn').addEventListener('click',()=>jsonDialog('Dataset versions and scope',state.metadata,'data-versions.json'));
$('reconnect').addEventListener('click',connect);
$('closeDialog').addEventListener('click',()=>$('dataDialog').close());
$('downloadBtn').addEventListener('click',()=>{const url=URL.createObjectURL(new Blob([JSON.stringify(state.json,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=state.filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
connect();
