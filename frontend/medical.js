/* Campus Medical Assistance — medical incidents only. */
const $ = (id) => document.getElementById(id);
const state = { token: localStorage.getItem('cer_token'), user: null, active: null,
  places: [], contacts: [], alerts: [], selected: null, selectedSnapshot: null, queueSnapshot: null, contactsSnapshot: null, staffSnapshot: null, authMode: 'login', timer: null };
try { state.active = JSON.parse(sessionStorage.getItem('medical_active') || 'null'); } catch { state.active = null; }

function escapeHtml(value) { return String(value ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function friendly(value) { return String(value || '').replaceAll('_',' ').replace(/\b\w/g, c => c.toUpperCase()); }
function placeName(id) { return state.places.find(p => p.id === id)?.name || 'Location not confirmed'; }
function phoneHref(value) { return 'tel:' + String(value || '').replace(/[^+\d]/g, ''); }
function toast(message, isError=false) { const el=$('toast'); el.textContent=message; el.classList.toggle('error',isError); el.classList.remove('hidden'); clearTimeout(toast.timer); toast.timer=setTimeout(()=>el.classList.add('hidden'),5500); }
function setBusy(button, busy, label) { button.disabled=busy; if (busy) { button.dataset.label=button.textContent; button.textContent=label; } else if (button.dataset.label) { button.textContent=button.dataset.label; delete button.dataset.label; } }

async function api(path, options={}) {
  if (window.CER_CONFIG?.isApiConfigured && !window.CER_CONFIG.isApiConfigured()) {
    throw new Error('Live response service is not connected to this site.');
  }
  const headers = new Headers(options.headers || {});
  if (state.token) headers.set('Authorization', `Bearer ${state.token}`);
  if (options.json !== undefined) { headers.set('Content-Type','application/json'); options.body=JSON.stringify(options.json); }
  // Use config for API URL (supports GitHub Pages deployment with separate API)
  const apiBaseUrl = window.CER_CONFIG?.getApiUrl ? window.CER_CONFIG.getApiUrl(path) : `/api/v1${path}`;
  const res=await fetch(apiBaseUrl, {...options,headers});
  const data=await res.json().catch(()=>({}));
  if (!res.ok) {
    const detail=typeof data.detail==='string' ? data.detail : `Request failed (${res.status})`;
    throw new Error(detail);
  }
  return data;
}
function activeHeaders() { return state.active?.guest_token ? {'X-Alert-Token':state.active.guest_token} : {}; }
function saveActive(data, key) { state.active={id:data.id, guest_token:data.guest_token || null, key}; sessionStorage.setItem('medical_active',JSON.stringify(state.active)); }

function showView() {
  const role=state.user?.role;
  $('student-view').classList.toggle('hidden',role==='admin'||role==='responder');
  $('admin-view').classList.toggle('hidden',role!=='admin');
  $('staff-view').classList.toggle('hidden',role!=='responder');
  $('account-label').textContent=state.user ? `${state.user.name} · ${friendly(role)}` : 'Guest access';
  $('login-open').classList.toggle('hidden',!!state.user);
  $('logout').classList.toggle('hidden',!state.user);
  if (role==='admin') refreshAdmin();
  else if (role==='responder') refreshStaff();
  else if (state.active) refreshStudent();
}

async function startAlert(source) {
  if (state.active && !['resolved','closed_false_report'].includes(state.activeStatus || 'new')) {
    $('request-panel').scrollIntoView({behavior:'smooth',block:'start'});
    toast('Your current alert is already in the queue.');
    return;
  }
  const button=source==='self' ? $('help-button') : $('bystander-button');
  const key=sessionStorage.getItem('medical_pending_key') || crypto.randomUUID();
  sessionStorage.setItem('medical_pending_key',key);
  setBusy(button,true,'Sending alert…');
  try {
    const result=await api('/medical-alerts',{method:'POST',headers:{'Idempotency-Key':key},json:{source}});
    saveActive(result,key); sessionStorage.removeItem('medical_pending_key');
    $('request-panel').classList.remove('hidden');
    renderStudentStatus(result);
    $('request-panel').scrollIntoView({behavior:'smooth',block:'start'});
    toast('Your medical alert was received.');
    requestDeviceLocation();
  } catch(e) {
    toast(`Alert was not sent: ${e.message}. Call campus emergency services directly.`,true);
  } finally { setBusy(button,false); }
}

function renderStudentStatus(alert) {
  state.activeStatus=alert.status;
  $('request-panel').classList.remove('hidden');
  $('request-number').textContent=`#${alert.id}`;
  const labels={new:'Your alert has reached the admin queue.',acknowledged:'An admin is reviewing your request.',checking:'An admin is checking the details.',staff_alerted:'Campus staff have been contacted.',medical_dispatched:'The admin recorded medical team dispatch.',resolved:'This request has been marked resolved.',closed_false_report:'This request was closed after admin review.'};
  const banner=$('request-state'); banner.textContent=labels[alert.status]||friendly(alert.status); banner.classList.toggle('error',alert.status==='closed_false_report');
  const stages=['new','acknowledged','staff_alerted','medical_dispatched'];
  const stage=alert.status==='checking'?1:alert.status==='resolved'?3:Math.max(0,stages.indexOf(alert.status));
  ['new','acknowledged','staff','medical'].forEach((part,index)=>$('progress-'+part).classList.toggle('active',index<=stage));
}

async function refreshStudent() {
  if (!state.active) return;
  try {
    const alert=await api(`/medical-alerts/${state.active.id}/public`,{headers:activeHeaders()});
    renderStudentStatus(alert);
    const messages=await api(`/medical-alerts/${state.active.id}/messages`,{headers:activeHeaders()});
    renderMessages('student-messages',messages);
  } catch(e) { $('request-state').textContent=`Could not refresh request: ${e.message}`; $('request-state').classList.add('error'); }
}

function requestDeviceLocation() {
  if (!state.active || !navigator.geolocation || !window.isSecureContext) return;
  navigator.geolocation.getCurrentPosition(async (pos)=>{
    try { await api(`/medical-alerts/${state.active.id}/location`,{method:'PATCH',headers:activeHeaders(),json:{latitude:pos.coords.latitude,longitude:pos.coords.longitude,accuracy_m:pos.coords.accuracy}}); toast('Device location shared with the admin.'); }
    catch(e) { toast(`Location not shared: ${e.message}`,true); }
  },()=>{}, {enableHighAccuracy:false,timeout:6000,maximumAge:30000});
}

async function saveDetails(e) {
  e.preventDefault(); if (!state.active) return;
  const body={};
  if ($('place').value) body.place_name=$('place').value;
  for (const [field,id] of [['location_text','location-text'],['callback_phone','callback-phone'],['details','details']]) {
    const value=$(id).value.trim(); if (value) body[field]=value;
  }
  try { await api(`/medical-alerts/${state.active.id}/location`,{method:'PATCH',headers:activeHeaders(),json:body}); toast('Details shared with the admin.'); }
  catch(e) { toast(e.message,true); }
}

function renderMessages(id,messages) {
  const container=$(id);
  container.innerHTML=messages.length ? messages.map(m=>`<div class="message ${m.sender_kind==='admin'?'admin':'student'}"><small>${m.sender_kind==='admin'?'Admin':'Student'}</small>${escapeHtml(m.body)}</div>`).join('') : '<p class="muted">No messages yet.</p>';
  container.scrollTop=container.scrollHeight;
}
async function sendStudentMessage(e) {
  e.preventDefault(); const input=$('student-message'); const body=input.value.trim(); if(!body||!state.active)return;
  try { await api(`/medical-alerts/${state.active.id}/messages`,{method:'POST',headers:activeHeaders(),json:{body}}); input.value=''; refreshStudent(); }
  catch(err) { toast(err.message,true); }
}

async function refreshAdmin() {
  try {
    const [alerts,operations,contacts]=await Promise.all([api('/medical-alerts/admin/queue'),api('/campus/operations'),api('/campus/contacts')]);
    state.alerts=alerts; state.contacts=contacts;
    renderQueue(); renderContacts(); renderOperations(operations);
    if(state.selected) {
      const current=state.alerts.find(a=>a.id===state.selected);
      if(current && JSON.stringify(current)!==state.selectedSnapshot) await selectAlert(state.selected);
      else await Promise.all([loadEvents(state.selected),loadAdminMessages(state.selected)]);
    }
  } catch(e) { toast(`Could not load admin queue: ${e.message}`,true); }
}
function renderOperations(ops) {
  const pill=$('operations-pill'); pill.textContent=ops.live_ready?'Live contact setup ready':'Prototype / setup needed'; pill.classList.toggle('warn',!ops.live_ready);
  const issues=[]; if(ops.notification_mode!=='sns') issues.push('Outbound alerts are simulated.'); if(!ops.backup_configured) issues.push('Backup contact is missing.'); if(!ops.campus_emergency_phone_configured) issues.push('Campus emergency phone is missing.'); if(ops.failed_jobs) issues.push(`${ops.failed_jobs} notification job(s) failed.`);
  const warning=$('operations-warning'); warning.textContent=issues.join(' '); warning.classList.toggle('hidden',!issues.length);
}
function renderQueue(force=false) {
  const snapshot=JSON.stringify(state.alerts.map(a=>[a.id,a.status,a.place_id,a.location_text,a.claimed_by,a.verification,state.selected]));
  if(!force && snapshot===state.queueSnapshot)return;
  state.queueSnapshot=snapshot;
  const open=state.alerts.filter(a=>!['resolved','closed_false_report'].includes(a.status)); $('queue-count').textContent=open.length;
  $('admin-queue').innerHTML=state.alerts.length?state.alerts.map(a=>`<button type="button" class="queue-item ${state.selected===a.id?'selected':''}" data-alert-id="${a.id}"><span class="queue-top"><strong>Medical alert #${a.id}</strong><span class="status-tag ${escapeHtml(a.status)}">${friendly(a.status)}</span></span><span class="queue-meta"><span>${escapeHtml(placeName(a.place_id))}</span><span>${a.source==='bystander'?'Bystander':'Self'} · ${a.identity_verified?'Signed in':'Guest'}</span></span></button>`).join(''):'<div class="empty-list">No medical alerts yet.</div>';
  $('admin-queue').querySelectorAll('[data-alert-id]').forEach(button=>button.addEventListener('click',()=>selectAlert(Number(button.dataset.alertId))));
}

async function selectAlert(id) {
  const alert=state.alerts.find(a=>a.id===id); if(!alert)return;
  state.selected=id; state.selectedSnapshot=JSON.stringify(alert); renderQueue(true);
  const phone=alert.callback_phone?`<a href="${phoneHref(alert.callback_phone)}">${escapeHtml(alert.callback_phone)}</a>`:'Not provided';
  $('detail-id').textContent=`#${id}`;
  $('admin-detail').innerHTML=`<div class="detail-body"><div class="detail-heading"><h3>${alert.source==='bystander'?'Bystander report':'Student help request'}</h3><span class="status-tag ${escapeHtml(alert.status)}">${friendly(alert.status)}</span></div><dl class="detail-facts"><div><dt>Campus place</dt><dd>${escapeHtml(placeName(alert.place_id))}</dd></div><div><dt>Room / landmark</dt><dd>${escapeHtml(alert.location_text||'Not provided')}</dd></div><div><dt>Reporter</dt><dd>${alert.identity_verified?'Signed-in student':'Guest · identity unverified'}</dd></div><div><dt>Callback</dt><dd>${phone}</dd></div><div><dt>Verification</dt><dd>${friendly(alert.verification)}</dd></div><div><dt>Admin claim</dt><dd>${alert.claimed_by?'Claimed':'Unclaimed'}</dd></div></dl>${alert.details?`<p><strong>Details:</strong> ${escapeHtml(alert.details)}</p>`:''}${alert.latitude!==null&&alert.latitude!==undefined?`<p class="muted">Device position: ${Number(alert.latitude).toFixed(5)}, ${Number(alert.longitude).toFixed(5)} · accuracy ${Math.round(alert.accuracy_m||0)} m. Confirm the actual room before dispatch.</p>`:''}<div class="action-row"><button class="button button-navy" data-action="claim">Claim</button><button class="button button-soft" data-action="contact">Record contact</button><button class="button button-soft" data-action="verify">Confirm need</button><button class="button button-danger" data-action="dispatch-medical">Record medical dispatch</button><button class="button button-soft" data-action="resolve">Resolve</button><button class="button button-soft" data-action="close-false">Close false report</button></div><label for="action-note"><strong>Action note</strong> (required for contact, verification, dispatch, and closure)</label><textarea id="action-note" rows="2" placeholder="Who was contacted and what did they confirm?"></textarea><div class="detail-section"><h4>Alert nearby staff</h4><div class="inline-fields"><select id="staff-choice" aria-label="Choose staff contact"><option value="">Choose staff</option>${state.contacts.filter(c=>c.active).map(c=>`<option value="${c.id}">${escapeHtml(c.name)} · ${friendly(c.kind)} · ${friendly(c.shift)}</option>`).join('')}</select><button id="staff-send" class="button button-navy">Alert staff</button></div><p id="staff-suggestions" class="suggestions">Choose a contact or configure nearby coverage below.</p><a id="staff-call" class="call-link hidden" href="#">Call selected staff</a></div><div class="detail-section"><h4>Conversation</h4><div id="admin-messages" class="message-list detail-messages"></div><form id="admin-message-form" class="message-compose"><label class="sr-only" for="admin-message">Message to student</label><input id="admin-message" maxlength="1000" placeholder="Ask a short question"><button class="button button-navy" type="submit">Send</button></form></div><div class="detail-section"><h4>Activity</h4><ol id="event-list" class="timeline"></ol></div></div>`;
  $('admin-detail').querySelectorAll('[data-action]').forEach(button=>button.addEventListener('click',()=>adminAction(button.dataset.action)));
  $('staff-choice').addEventListener('change',()=>{const c=state.contacts.find(x=>x.id===Number($('staff-choice').value));const link=$('staff-call');link.classList.toggle('hidden',!c?.phone);if(c?.phone)link.href=phoneHref(c.phone);});
  $('staff-send').addEventListener('click',sendStaffAlert);
  $('admin-message-form').addEventListener('submit',sendAdminMessage);
  await Promise.all([loadEvents(id),loadAdminMessages(id),loadSuggestions(alert.place_id,id)]);
}
async function loadEvents(id) { try { const events=await api(`/medical-alerts/${id}/events`); if(state.selected!==id)return; $('event-list').innerHTML=events.length?events.map(e=>`<li><strong>${friendly(e.action)}</strong>${e.note?` · ${escapeHtml(e.note)}`:''}<small>${new Date(e.created_at).toLocaleString()}</small></li>`).join(''):'<li>No activity yet.</li>'; } catch(e){toast(e.message,true);} }
async function loadAdminMessages(id) { try {const messages=await api(`/medical-alerts/${id}/messages`);if(state.selected===id)renderMessages('admin-messages',messages);}catch(e){toast(e.message,true);} }
async function loadSuggestions(placeId,id) { if(!placeId)return; try {const rows=await api(`/campus/coverage/${placeId}`);if(state.selected!==id)return;$('staff-suggestions').textContent=rows.length?`Suggested: ${rows.map(r=>`${r.name}${r.on_duty?' (on duty)':' (off duty)'}`).join(', ')}`:'No coverage configured for this place. Choose a contact manually.';}catch(e){$('staff-suggestions').textContent='Could not load coverage.';} }

async function adminAction(action) {
  if(!state.selected)return; const note=$('action-note')?.value.trim()||'';
  let body={note}; if(action==='close-false') body={reason:note};
  if(action!=='claim' && note.length<(action==='close-false'?10:2)) {toast('Write a clear action note first.',true);$('action-note').focus();return;}
  try {await api(`/medical-alerts/${state.selected}/${action}`,{method:'POST',json:action==='claim'?{}:body});toast('Action recorded.');await refreshAdmin();}
  catch(e){toast(e.message,true);}
}
async function sendStaffAlert() { const staffId=Number($('staff-choice').value);if(!staffId){toast('Choose a staff contact.',true);return;}try{await api(`/medical-alerts/${state.selected}/staff`,{method:'POST',json:{staff_id:staffId}});toast('Staff alert recorded. Delivery status appears in operations.');refreshAdmin();}catch(e){toast(e.message,true);} }
async function sendAdminMessage(e) {e.preventDefault();const body=$('admin-message').value.trim();if(!body)return;try{await api(`/medical-alerts/${state.selected}/messages`,{method:'POST',json:{body}});$('admin-message').value='';loadAdminMessages(state.selected);}catch(err){toast(err.message,true);} }

function renderContacts() {
  const snapshot=JSON.stringify(state.contacts);
  if(snapshot===state.contactsSnapshot)return;
  state.contactsSnapshot=snapshot;
  $('contact-list').innerHTML=state.contacts.length?state.contacts.map(c=>`<div class="contact-item"><strong>${escapeHtml(c.name)}</strong><small>${friendly(c.kind)} · ${friendly(c.shift)} shift${c.active?'':' · inactive'}</small>${c.phone?`<a href="${phoneHref(c.phone)}">${escapeHtml(c.phone)}</a>`:'<small>No phone configured</small>'}<details><summary>Edit contact</summary><form class="contact-edit" data-contact-id="${c.id}"><label>Phone<input type="tel" name="phone" value="${escapeHtml(c.phone||'')}"></label><label>Shift<select name="shift"><option value="all" ${c.shift==='all'?'selected':''}>All hours</option><option value="day" ${c.shift==='day'?'selected':''}>Day</option><option value="night" ${c.shift==='night'?'selected':''}>Night</option></select></label><label class="contact-active"><input type="checkbox" name="active" ${c.active?'checked':''}> Available for alerts</label><button class="button button-navy" type="submit">Save contact</button></form></details></div>`).join(''):'<p class="muted">Add a staff contact to start routing alerts.</p>';
  $('contact-list').querySelectorAll('.contact-edit').forEach(form=>form.addEventListener('submit',updateContact));
  $('coverage-staff').innerHTML='<option value="">Choose contact</option>'+state.contacts.map(c=>`<option value="${c.id}">${escapeHtml(c.name)}</option>`).join('');
}
async function createContact(e){e.preventDefault();const body={name:$('contact-name').value.trim(),kind:$('contact-kind').value,phone:$('contact-phone').value.trim()||null,shift:$('contact-shift').value};if($('contact-email').value.trim()){body.email=$('contact-email').value.trim();body.password=$('contact-password').value;}try{await api('/campus/contacts',{method:'POST',json:body});$('contact-form').reset();toast('Contact added.');refreshAdmin();}catch(err){toast(err.message,true);} }
async function updateContact(e){e.preventDefault();const form=e.currentTarget;const body={phone:form.elements.phone.value.trim()||null,shift:form.elements.shift.value,active:form.elements.active.checked};try{await api(`/campus/contacts/${form.dataset.contactId}`,{method:'PATCH',json:body});toast('Contact updated.');refreshAdmin();}catch(err){toast(err.message,true);} }
async function saveCoverage(e){e.preventDefault();const body={place_id:Number($('coverage-place').value),staff_id:Number($('coverage-staff').value),rank:Number($('coverage-rank').value)};if(!body.place_id||!body.staff_id){toast('Choose a place and contact.',true);return;}try{await api('/campus/coverage',{method:'POST',json:body});toast('Coverage saved.');if(state.selected)selectAlert(state.selected);}catch(err){toast(err.message,true);} }

async function refreshStaff(){try{const alerts=await api('/medical-alerts/staff/inbox');const snapshot=JSON.stringify(alerts);if(snapshot===state.staffSnapshot)return;state.staffSnapshot=snapshot;$('staff-inbox').innerHTML=alerts.length?alerts.map(a=>`<article class="panel staff-card"><h2>Medical alert #${a.id}</h2><p>${escapeHtml(placeName(a.place_id))}${a.location_text?' · '+escapeHtml(a.location_text):''}</p><p><span class="status-tag ${escapeHtml(a.status)}">${friendly(a.status)}</span></p><button class="button button-navy" data-ack="${a.id}" ${a.assignment_status==='acknowledged'?'disabled':''}>${a.assignment_status==='acknowledged'?'Acknowledged':'Acknowledge'}</button><label for="finding-${a.id}" class="sr-only">Findings for alert ${a.id}</label><textarea id="finding-${a.id}" rows="2" placeholder="What did you find at the scene?"></textarea><button class="button button-soft" data-findings="${a.id}">Send findings</button></article>`).join(''):'<div class="panel empty-list">No alerts assigned to you.</div>';$('staff-inbox').querySelectorAll('[data-ack]').forEach(b=>b.addEventListener('click',async()=>{try{await api(`/medical-alerts/${b.dataset.ack}/staff/acknowledge`,{method:'POST'});b.disabled=true;b.textContent='Acknowledged';toast('Acknowledgement sent.');}catch(e){toast(e.message,true);}}));$('staff-inbox').querySelectorAll('[data-findings]').forEach(b=>b.addEventListener('click',async()=>{const body=$('finding-'+b.dataset.findings).value.trim();if(body.length<2){toast('Enter your findings first.',true);return;}try{await api(`/medical-alerts/${b.dataset.findings}/staff/findings`,{method:'POST',json:{findings:body}});toast('Findings sent to admin.');}catch(e){toast(e.message,true);}}));}catch(e){toast(e.message,true);} }

function openAuth(){ $('auth-dialog').showModal();$('auth-email').focus(); }
function setAuthMode(mode){state.authMode=mode;const register=mode==='register';$('auth-title').textContent=register?'Create student account':'Sign in';$('register-name-wrap').classList.toggle('hidden',!register);$('auth-submit').textContent=register?'Create account':'Sign in';$('auth-switch').textContent=register?'Already have an account? Sign in':'Create a student account';$('auth-error').classList.add('hidden');}
async function handleAuth(e){e.preventDefault();const email=$('auth-email').value.trim();const password=$('auth-password').value;const error=$('auth-error');error.classList.add('hidden');try{if(state.authMode==='register'){await api('/auth/register',{method:'POST',json:{name:$('auth-name').value.trim(),email,password}});}const form=new URLSearchParams({username:email,password});const result=await api('/auth/login',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:form});state.token=result.access_token;localStorage.setItem('cer_token',state.token);state.user=await api('/auth/me');$('auth-dialog').close();showView();toast(`Signed in as ${state.user.name}.`);}catch(err){error.textContent=err.message;error.classList.remove('hidden');} }
async function restoreSession(){if(!state.token)return;try{state.user=await api('/auth/me');}catch{state.token=null;localStorage.removeItem('cer_token');}}

async function init(){
  $('help-button').addEventListener('click',()=>startAlert('self'));
  $('bystander-button').addEventListener('click',()=>startAlert('bystander'));
  $('details-form').addEventListener('submit',saveDetails);
  $('share-location').addEventListener('click',requestDeviceLocation);
  $('student-message-form').addEventListener('submit',sendStudentMessage);
  $('login-open').addEventListener('click',openAuth);
  $('auth-close').addEventListener('click',()=>$('auth-dialog').close());
  $('auth-switch').addEventListener('click',()=>setAuthMode(state.authMode==='login'?'register':'login'));
  $('auth-form').addEventListener('submit',handleAuth);
  $('logout').addEventListener('click',()=>{state.token=null;state.user=null;localStorage.removeItem('cer_token');showView();toast('Signed out.');});
  $('contact-form').addEventListener('submit',createContact);
  $('coverage-form').addEventListener('submit',saveCoverage);
  if (window.CER_CONFIG?.isApiConfigured && !window.CER_CONFIG.isApiConfigured()) {
    toast('Live response service is not connected. Call campus emergency services directly.', true);
  } else { try{const [places,config]=await Promise.all([api('/medical-alerts/places'),api('/medical-alerts/config')]);state.places=places;const options=places.map(p=>`<option value="${escapeHtml(p.name)}">${escapeHtml(p.name)}</option>`).join('');$('place').insertAdjacentHTML('beforeend',options);$('coverage-place').innerHTML='<option value="">Choose place</option>'+places.map(p=>`<option value="${p.id}">${escapeHtml(p.name)}</option>`).join('');if(config.campus_emergency_phone){const link=$('emergency-call');link.href=phoneHref(config.campus_emergency_phone);link.textContent=`Call campus emergency services: ${config.campus_emergency_phone}`;link.classList.remove('hidden');}}catch(e){toast(`Could not load campus places: ${e.message}`,true);}}
  await restoreSession();showView();
  state.timer=setInterval(()=>{if(state.user?.role==='admin')refreshAdmin();else if(state.user?.role==='responder')refreshStaff();else if(state.active)refreshStudent();},5000);
}
document.addEventListener('DOMContentLoaded',init);

