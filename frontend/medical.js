/* Campus Medical Assistance — medical incidents only. */
const $ = (id) => document.getElementById(id);
const state = { token: localStorage.getItem('cer_token'), user: null, active: null,
  places: [], contacts: [], alerts: [], selected: null, selectedSnapshot: null, queueSnapshot: null, contactsSnapshot: null, staffSnapshot: null, authMode: 'login', timer: null, actionDrafts: {}, detailTab: 'overview', autoDemoRunning: false };
try { state.active = JSON.parse(sessionStorage.getItem('medical_active') || 'null'); } catch { state.active = null; }

function escapeHtml(value) { return String(value ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function friendly(value) { return String(value || '').replaceAll('_',' ').replace(/\b\w/g, c => c.toUpperCase()); }
function placeName(id) { return state.places.find(p => p.id === id)?.name || 'Location not confirmed'; }
function phoneHref(value) { return String(value || '').startsWith('DEMO-') ? '#' : 'tel:' + String(value || '').replace(/[^+\d]/g, ''); }
function renderLocationMap(container,lat,lon) {
  if(lat==null||lon==null){container.replaceChildren();return;}
  const latitude=Number(lat),longitude=Number(lon);if(!Number.isFinite(latitude)||!Number.isFinite(longitude))return;
  const box=[longitude-.002,latitude-.002,longitude+.002,latitude+.002].join(',');
  const details=document.createElement('details'),summary=document.createElement('summary');summary.textContent='Show location on map';details.append(summary);
  const note=document.createElement('p');note.className='muted';note.textContent='Opening the map shares these coordinates with OpenStreetMap.';details.append(note);
  details.addEventListener('toggle',()=>{if(!details.open||details.querySelector('iframe'))return;const frame=document.createElement('iframe');frame.title='Reported location on OpenStreetMap';frame.loading='lazy';frame.referrerPolicy='no-referrer';frame.src=`https://www.openstreetmap.org/export/embed.html?bbox=${encodeURIComponent(box)}&marker=${encodeURIComponent(latitude+','+longitude)}&layer=mapnik`;details.append(frame);});
  container.replaceChildren(details);
}
function toast(message, isError=false) { const el=$('toast'); el.textContent=message; el.classList.toggle('error',isError); el.classList.remove('hidden'); clearTimeout(toast.timer); toast.timer=setTimeout(()=>el.classList.add('hidden'),5500); }
function setBusy(button, busy, label) { button.disabled=busy; if (busy) { button.dataset.label=button.textContent; button.textContent=label; } else if (button.dataset.label) { button.textContent=button.dataset.label; delete button.dataset.label; } }
function userMessage(error) { const text=String(error?.message||''); if(text.includes('fetch')) return 'The response service could not be reached. Call campus emergency services directly.'; if(text.includes('already exists')) return 'An account already exists for this email. Sign in instead.'; if(text.includes('Alert changed')) return 'This alert was updated by another admin. The queue has been refreshed.'; return 'We could not save that update. Please try again.'; }

async function api(path, options={}) {
  if (window.CER_CONFIG?.isApiConfigured && !window.CER_CONFIG.isApiConfigured()) {
    throw new Error('Live response service is not connected to this site');
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
    const error=new Error(detail); error.status=res.status; throw error;
  }
  return data;
}
function activeHeaders() { return state.active?.guest_token ? {'X-Alert-Token':state.active.guest_token} : {}; }
function saveActive(data, key) { state.active={id:data.id, guest_token:data.guest_token || null, key, status:data.status || 'new'}; state.detailsDirty=false; state.detailsLoadedFor=null; $('details-form').reset(); sessionStorage.setItem('medical_active',JSON.stringify(state.active)); }

function showView() {
  const role=state.user?.role;
  $('student-view').classList.toggle('hidden',role==='admin');
  $('admin-view').classList.toggle('hidden',role!=='admin');
  $('account-label').textContent=state.user ? `${state.user.name} · ${friendly(role)}` : 'Guest access';
  $('login-open').classList.toggle('hidden',!!state.user);
  $('logout').classList.toggle('hidden',!state.user);
  if (state.demoReady && role==='admin') refreshAdmin();
  else if (state.demoReady && state.active) refreshStudent();
}

async function startAlert(source) {
  if(!state.demoReady){toast('Demo service is unavailable or not safely configured. For a real emergency, call emergency services directly.',true);return;}
  if (state.active && !['resolved','closed_false_report'].includes(state.active.status || 'new')) {
    try { await api(`/medical-alerts/${state.active.id}/escalate`,{method:'POST',headers:activeHeaders()}); toast('Urgent follow-up was recorded for the admin.'); }
    catch(e) { if(e.status===404){state.active=null;sessionStorage.removeItem('medical_active');$('request-panel').classList.add('hidden');toast('That demo was reset. Press the button again to start a new demo.');}else toast(userMessage(e),true); }
    $('request-panel').scrollIntoView({behavior:'smooth',block:'start'});
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
    if(e.status===410) sessionStorage.removeItem('medical_pending_key');
    toast(userMessage(e),true);
  } finally { setBusy(button,false); }
}

function renderStudentStatus(alert) {
  if (state.active) { state.active.status=alert.status; sessionStorage.setItem('medical_active',JSON.stringify(state.active)); }
  state.activeStatus=alert.status;
  $('request-panel').classList.remove('hidden');
  $('request-number').textContent=`#${alert.id}`;
  if(Array.isArray(alert.history) && state.detailsLoadedFor!==alert.id && !state.detailsDirty){
    const selected=state.places.find(place=>place.id===alert.place_id);$('place').value=selected?.name||'';
    $('location-text').value=alert.location_text||'';$('callback-phone').value=alert.callback_phone||'';$('details').value=alert.details||'';
    state.detailsLoadedFor=alert.id;
  }
  const labels={new:'Your alert has reached the demo admin queue.',acknowledged:'An admin is reviewing your demo request.',checking:'An admin is checking the details.',contact_pending:'A demo contact attempt is pending. No real call or message was sent.',staff_alerted:'A demo contact accepted. No one was contacted.',medical_dispatched:'Medical Team Dispatched — DEMO. No real team was dispatched.',en_route:'Team en route — DEMO. No real team is travelling.',arrived:'Team arrived — DEMO. No real team has arrived.',resolved:'This demo request has been marked resolved.',closed_false_report:'This request was closed after admin review.'};
  const banner=$('request-state'); banner.textContent=labels[alert.status]||friendly(alert.status); banner.classList.toggle('error',alert.status==='closed_false_report');
  $('status-updated').textContent=alert.updated_at?`Last updated: ${new Date(alert.updated_at).toLocaleString()}`:'';
  $('demo-team').textContent=alert.demo_team?`Fictional demo team: ${alert.demo_team}. No real responder has been contacted.`:'';$('demo-team').classList.toggle('hidden',!alert.demo_team);
  $('location-state').textContent=alert.latitude!=null&&alert.longitude!=null?`Device location saved: ${Number(alert.latitude).toFixed(5)}, ${Number(alert.longitude).toFixed(5)}. Add a room or landmark if possible.`:alert.place_id||alert.location_text?'Manual location saved with this demo alert.':'Location not yet shared. Choose your campus location below.';
  const mapKey=`${alert.latitude},${alert.longitude}`;if($('student-map').dataset.location!==mapKey){$('student-map').dataset.location=mapKey;renderLocationMap($('student-map'),alert.latitude,alert.longitude);}
  const stage={new:'new',acknowledged:'acknowledged',checking:'acknowledged',contact_pending:'acknowledged',staff_alerted:'staff',medical_dispatched:'medical',en_route:'en-route',arrived:'arrived',resolved:'resolved'}[alert.status];
  const labelsByStage={new:'Alert received',acknowledged:'Admin reviewing',staff:'Demo contact accepted',medical:'Demo dispatch','en-route':'Demo en route',arrived:'Demo arrived',resolved:'Resolved'};
  ['new','acknowledged','staff','medical','en-route','arrived','resolved'].forEach(part=>{const el=$('progress-'+part),event=(alert.history||[]).find(entry=>entry.stage===part);el.classList.toggle('active',part===stage);el.classList.toggle('completed',!!event&&part!==stage);el.textContent=labelsByStage[part];if(event?.created_at){const time=document.createElement('small');time.textContent=new Date(event.created_at).toLocaleString();el.append(time);}if(part===stage)el.setAttribute('aria-current','step');else el.removeAttribute('aria-current');});
}

async function refreshStudent() {
  if (!state.active) return;
  try {
    const alert=await api(`/medical-alerts/${state.active.id}/public`,{headers:activeHeaders()});
    renderStudentStatus(alert);
    if (window.CER_CONFIG?.FEATURES?.ENABLE_MESSAGES) {
      const messages=await api(`/medical-alerts/${state.active.id}/messages`,{headers:activeHeaders()});
      renderMessages('student-messages',messages);
    }
  } catch(e) { if(e.status===404){state.active=null;sessionStorage.removeItem('medical_active');$('request-panel').classList.add('hidden');toast('This demo alert was cleared. You can start a new demo.');return;} $('request-state').textContent=`Could not refresh request: ${e.message}`; $('request-state').classList.add('error'); }
}

function requestDeviceLocation() {
  if (!state.active) return;
  if (!navigator.geolocation || !window.isSecureContext) { const message='Device location needs HTTPS or localhost and a supported browser. Enter your campus location manually.';$('location-feedback').textContent=message;toast(message,true); return; }
  const button=$('share-location'); setBusy(button,true,'Finding location…');
  $('location-feedback').textContent='Requesting device location. You can enter a location manually while you wait.';
  navigator.geolocation.getCurrentPosition(async (pos)=>{
    try { await api(`/medical-alerts/${state.active.id}/location`,{method:'PATCH',headers:activeHeaders(),json:{latitude:pos.coords.latitude,longitude:pos.coords.longitude,accuracy_m:pos.coords.accuracy}}); $('location-feedback').textContent='Device location saved to this demo alert.';toast('Device location saved to this demo alert.'); await refreshStudent(); }
    catch(e) { $('location-feedback').textContent='Location could not be saved. Enter your campus location manually.';toast($('location-feedback').textContent,true); }
    finally { setBusy(button,false); }
  },(error)=>{ setBusy(button,false);const reason=error.code===1?'Location permission denied':error.code===3?'Location request timed out':'Device location unavailable';$('location-feedback').textContent=`${reason}. Please enter your campus location manually.`;toast($('location-feedback').textContent,true); }, {enableHighAccuracy:false,timeout:6000,maximumAge:30000});
}

async function saveDetails(e) {
  e.preventDefault(); if (!state.active) return;
  const body={};
  if ($('place').value) body.place_name=$('place').value;
  for (const [field,id] of [['location_text','location-text'],['callback_phone','callback-phone'],['details','details']]) {
    const value=$(id).value.trim(); if (value) body[field]=value;
  }
  try { await api(`/medical-alerts/${state.active.id}/location`,{method:'PATCH',headers:activeHeaders(),json:body}); $('details-feedback').textContent='Details saved to this demo alert.';toast('Details shared with the admin.'); await refreshStudent(); }
  catch(e) { $('details-feedback').textContent='Details were not saved. Your entries remain here; please try again.';toast(userMessage(e),true); }
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
    renderQueue(); renderContacts(); renderContactAssignments(); renderOperations(operations);
    if(state.selected) {
      const current=state.alerts.find(a=>a.id===state.selected);
      if(current && JSON.stringify(current)!==state.selectedSnapshot) await selectAlert(state.selected);
      else await loadEvents(state.selected);
    }
  } catch(e) { toast(`Could not load admin queue: ${e.message}`,true); }
}
function renderOperations(ops) {
  const pill=$('operations-pill'); pill.textContent=ops.live_ready?'Live contact setup ready':'Prototype / setup needed'; pill.classList.toggle('warn',!ops.live_ready);
  const issues=[]; if(ops.notification_mode!=='sns') issues.push('Outbound alerts are simulated.'); if(!ops.backup_configured) issues.push('Backup contact is missing.'); if(!ops.campus_emergency_phone_configured) issues.push('Campus emergency phone is missing.'); if(ops.failed_jobs) issues.push(`${ops.failed_jobs} notification job(s) failed.`);
  const warning=$('operations-warning'); warning.textContent=issues.join(' '); warning.classList.toggle('hidden',!issues.length);
}
function renderQueue(force=false) {
  const query=$('queue-search').value.trim().toLowerCase(), filter=$('queue-filter').value;
  const snapshot=JSON.stringify([state.alerts,state.selected,query,filter]);
  if(!force && snapshot===state.queueSnapshot)return;
  state.queueSnapshot=snapshot;
  const open=state.alerts.filter(a=>!['resolved','closed_false_report'].includes(a.status)); $('queue-count').textContent=open.length;
  const dispatched=['medical_dispatched','en_route','arrived'];
  const cards=[['New alerts',state.alerts.filter(a=>a.status==='new').length],['Active emergencies',open.length],['Awaiting verification',open.filter(a=>a.verification!=='confirmed_need').length],['Demo teams dispatched',open.filter(a=>dispatched.includes(a.status)).length],['Resolved cases',state.alerts.filter(a=>a.status==='resolved').length]];
  $('dashboard-overview').innerHTML=cards.map(([label,count])=>`<div class="overview-card"><span>${label}</span><strong>${count}</strong></div>`).join('');
  const shown=state.alerts.filter(a=>{const closed=['resolved','closed_false_report'].includes(a.status);if(filter==='open'&&closed||filter==='closed'&&!closed||filter==='unverified'&&(closed||a.verification==='confirmed_need')||filter==='dispatched'&&!dispatched.includes(a.status))return false;return `${a.id} ${placeName(a.place_id)} ${a.location_text||''} ${a.status}`.toLowerCase().includes(query);});
  $('admin-queue').innerHTML=shown.length?shown.map(a=>`<button type="button" class="queue-item ${state.selected===a.id?'selected':''}" data-alert-id="${a.id}"><span class="queue-top"><strong>Demo alert #${a.id}</strong><span class="status-tag ${escapeHtml(a.status)}">${friendly(a.status)}</span></span><span class="queue-meta"><span>${escapeHtml(placeName(a.place_id))}</span><span>${a.source==='bystander'?'Bystander':'Self'} · ${a.identity_verified?'Signed in':'Guest'}</span></span><span class="queue-meta"><span>${a.place_id||a.location_text||a.latitude!=null?'Location supplied · unconfirmed':'⚠ Location missing'}</span><span>${a.created_at?escapeHtml(new Date(a.created_at).toLocaleString()):''}</span></span></button>`).join(''):'<div class="empty-list">No alerts match this view.</div>';
  $('admin-queue').querySelectorAll('[data-alert-id]').forEach(button=>button.addEventListener('click',()=>selectAlert(Number(button.dataset.alertId))));
}

async function selectAlert(id) {
  const alert=state.alerts.find(a=>a.id===id); if(!alert)return;
  state.selected=id; state.selectedSnapshot=JSON.stringify(alert); renderQueue(true);
  const phone=alert.callback_phone?escapeHtml(alert.callback_phone):'Not provided';
  $('detail-id').textContent=`#${id}`;
  $('admin-detail').classList.remove('empty-detail');
  $('admin-detail').innerHTML=`<div class="detail-body"><div class="detail-heading"><h3>${alert.source==='bystander'?'Bystander report':'Student help request'}</h3><span class="status-tag ${escapeHtml(alert.status)}">${friendly(alert.status)}</span></div><dl class="detail-facts"><div><dt>Campus place</dt><dd>${escapeHtml(placeName(alert.place_id))}</dd></div><div><dt>Room / landmark</dt><dd>${escapeHtml(alert.location_text||'Not provided')}</dd></div><div><dt>Reporter</dt><dd>${alert.identity_verified?'Signed-in student':'Guest · identity unverified'}</dd></div><div><dt>Callback</dt><dd>${phone}</dd></div><div><dt>Verification</dt><dd>${friendly(alert.verification)}</dd></div><div><dt>Admin claim</dt><dd>${alert.claimed_by?'Claimed':'Unclaimed'}</dd></div></dl>${alert.details?`<p><strong>Details:</strong> ${escapeHtml(alert.details)}</p>`:''}${alert.latitude!==null&&alert.latitude!==undefined?`<p class="muted">Device position: ${Number(alert.latitude).toFixed(5)}, ${Number(alert.longitude).toFixed(5)} · ${alert.accuracy_m == null ? 'accuracy unavailable' : `accuracy approximately ${Math.round(alert.accuracy_m)} m`}. Confirm the actual room before dispatch.</p>`:''}<div class="action-row"><button class="button button-navy" data-action="claim">Claim</button><button class="button button-soft" data-action="contact">Record contact</button><button class="button button-soft" data-action="verify">Confirm need</button><button class="button button-danger" data-action="dispatch-medical">Record medical dispatch</button><button class="button button-soft" data-action="resolve">Resolve</button><button class="button button-soft" data-action="close-false">Close false report</button></div><label for="action-note"><strong>Action note</strong> (required for contact, verification, dispatch, and closure)</label><textarea id="action-note" rows="2" placeholder="Who was contacted and what did they confirm?"></textarea><div class="detail-section"><h4>Alert nearby staff</h4><div class="inline-fields"><select id="staff-choice" aria-label="Choose staff contact"><option value="">Choose staff</option>${state.contacts.filter(c=>c.active).map(c=>`<option value="${c.id}">${escapeHtml(c.name)} · ${friendly(c.kind)} · ${friendly(c.shift)}</option>`).join('')}</select><button id="staff-send" class="button button-navy">Alert staff</button></div><p id="staff-suggestions" class="suggestions">Choose a contact or configure nearby coverage below.</p><a id="staff-call" class="call-link hidden" href="#">Call selected staff</a></div><div class="detail-section"><h4>Conversation</h4><div id="admin-messages" class="message-list detail-messages"></div><form id="admin-message-form" class="message-compose"><label class="sr-only" for="admin-message">Message to student</label><input id="admin-message" maxlength="1000" placeholder="Ask a short question"><button class="button button-navy" type="submit">Send</button></form></div><div class="detail-section"><h4>Activity</h4><ol id="event-list" class="timeline"></ol></div></div>`;
  $('admin-detail').querySelectorAll('[data-action]').forEach(button=>button.addEventListener('click',()=>adminAction(button.dataset.action)));
  const locationWarning=document.createElement('p'); locationWarning.className='location-state';
  const hasCoordinates=alert.latitude!=null&&alert.longitude!=null;
  locationWarning.textContent=!(hasCoordinates||alert.place_id||alert.location_text) ? 'Location missing — ask the reporter for a campus place, room or landmark.' : hasCoordinates&&alert.accuracy_m!=null&&Number(alert.accuracy_m)>100 ? 'Approximate GPS location may be imprecise — confirm the campus place and room.' : 'Location is not confirmed — verify the campus place and room or landmark.';
  $('admin-detail').querySelector('.detail-facts').after(locationWarning);
  if(alert.contact_name){const team=document.createElement('p');team.className='demo-team';const outcome=alert.status==='contact_pending'?'Awaiting simulated response':friendly(alert.contact_outcome||'pending');team.textContent=`Demo contact: ${alert.contact_name} · ${outcome} (simulated)`;$('admin-detail').querySelector('.detail-facts').after(team);}
  $('action-note').value=state.actionDrafts[id]||'';
  $('action-note').addEventListener('input',event=>{state.actionDrafts[id]=event.target.value;});
  const closed=['resolved','closed_false_report'].includes(alert.status), reviewing=['new','acknowledged','checking'].includes(alert.status), accepted=['staff_alerted','medical_dispatched','en_route','arrived'].includes(alert.status);
  for(const button of $('admin-detail').querySelectorAll('[data-action]')) {const action=button.dataset.action;button.disabled=closed || (['claim','contact'].includes(action)&&!reviewing) || (action==='dispatch-medical'&&alert.status!=='staff_alerted');}
  const verifySection=document.createElement('div');verifySection.className='detail-section';verifySection.innerHTML='<h4>Verification</h4><p class="muted">A guest or missing details do not mean a false report. Record your review in the action note.</p><label for="verification-choice">Review outcome</label><select id="verification-choice"><option value="in_progress">Verification in progress</option><option value="confirmed_need">Verified</option><option value="suspected_false">Suspected false report</option></select><button id="verification-save" class="button button-soft" type="button">Save verification</button>'; $('admin-detail').querySelector('.detail-facts').after(verifySection); $('verification-save').addEventListener('click',saveVerification);
  if(alert.latitude!=null && alert.longitude!=null) { const map=document.createElement('a'); map.className='button button-soft'; map.target='_blank'; map.rel='noopener noreferrer'; map.href=`https://www.openstreetmap.org/?mlat=${encodeURIComponent(alert.latitude)}&mlon=${encodeURIComponent(alert.longitude)}#map=18/${encodeURIComponent(alert.latitude)}/${encodeURIComponent(alert.longitude)}`; map.textContent='Open reported location on map'; $('admin-detail').querySelector('.detail-facts').after(map); }
  if(alert.latitude!=null && alert.longitude!=null){const mapPanel=document.createElement('div');mapPanel.className='map-panel';$('admin-detail').querySelector('.detail-facts').after(mapPanel);renderLocationMap(mapPanel,alert.latitude,alert.longitude);}
  $('staff-choice').addEventListener('change',()=>{ $('staff-call').classList.add('hidden'); });
  const method=document.createElement('select');method.id='demo-contact-method';method.setAttribute('aria-label','Simulated contact method');method.innerHTML='<option value="notification">Simulate notification</option><option value="call">Simulate call</option>'; $('staff-send').before(method);$('staff-send').textContent='Start simulation';
  $('admin-detail').querySelector('[data-action="dispatch-medical"]').textContent='Simulate medical dispatch';
  $('staff-send').addEventListener('click',sendStaffAlert);
  $('staff-send').disabled=closed || !reviewing;
  const autoDemo=document.createElement('button');autoDemo.type='button';autoDemo.className='button button-soft';autoDemo.textContent=state.autoDemoRunning?'Automatic demo running…':'Run automatic presentation';autoDemo.disabled=state.autoDemoRunning||!reviewing;autoDemo.addEventListener('click',runAutomaticDemo);
  const autoDescription=document.createElement('p');autoDescription.className='muted';autoDescription.textContent='Choose a demo contact first. Runs while this page stays open; no real contact or dispatch occurs.';
  $('staff-send').closest('.detail-section').append(autoDemo,autoDescription);
  if (['medical_dispatched','en_route','arrived'].includes(alert.status)) {
    const next=document.createElement('button'); next.type='button'; next.className='button button-navy'; next.textContent={'medical_dispatched':'Simulate team en route','en_route':'Simulate team arrived','arrived':'Resolve demo request'}[alert.status];
    next.addEventListener('click',()=>adminAction('demo-progress')); $('staff-send').parentElement.after(next);
  }
  const responseSection=$('admin-message-form')?.closest('.detail-section');
  if (responseSection) {
    responseSection.innerHTML='<h4>Demo staff response</h4><p class="muted">Record a fictional response for the demo. No call or message is sent.</p><div class="action-row"><button id="record-staff-ack" class="button button-soft" type="button">Simulate acknowledgement</button></div><label for="staff-findings"><strong>Demo findings</strong></label><textarea id="staff-findings" rows="2" placeholder="Enter fictional findings"></textarea><button id="record-staff-findings" class="button button-navy" type="button">Record demo findings</button>';
    $('record-staff-ack').addEventListener('click',()=>recordStaffResponse('staff-acknowledged'));
    $('record-staff-findings').addEventListener('click',()=>recordStaffResponse('staff-findings'));
    $('record-staff-ack').disabled=closed||!accepted; $('record-staff-findings').disabled=closed||!accepted;
  }
  organizeAlertDetails(verifySection,responseSection);
  await Promise.all([loadEvents(id),window.CER_CONFIG?.FEATURES?.ENABLE_MESSAGES?loadAdminMessages(id):Promise.resolve(),loadSuggestions(alert.place_id,id)]);
}
function organizeAlertDetails(verification,responseSection){
  const body=$('admin-detail').querySelector('.detail-body'),facts=body.querySelector('.detail-facts'),actions=body.querySelector('.action-row'),staff=$('staff-choice').closest('.detail-section'),activity=$('event-list').closest('.detail-section');
  const noteLabel=body.querySelector('label[for="action-note"]'),note=$('action-note'),header=body.querySelector('.detail-heading');
  const map=body.querySelector('.map-panel'),mapLink=[...body.querySelectorAll('a')].find(a=>a.textContent==='Open reported location on map');
  const progress=[...body.querySelectorAll('button')].find(button=>['Simulate team en route','Simulate team arrived','Resolve demo request'].includes(button.textContent));
  const nav=document.createElement('div');nav.className='detail-tabs';nav.setAttribute('role','tablist');nav.setAttribute('aria-label','Alert details');
  const panels={overview:document.createElement('section'),verification:document.createElement('section'),dispatch:document.createElement('section'),activity:document.createElement('section')};
  const labels={overview:'Overview',verification:'Verification',dispatch:'Contact & dispatch',activity:'Activity'};
  for(const [key,panel] of Object.entries(panels)){panel.id=`detail-panel-${key}`;panel.setAttribute('role','tabpanel');panel.setAttribute('aria-labelledby',`detail-tab-${key}`);const button=document.createElement('button');button.type='button';button.id=`detail-tab-${key}`;button.setAttribute('role','tab');button.setAttribute('aria-controls',panel.id);button.textContent=labels[key];button.addEventListener('click',()=>{state.detailTab=key;showDetailTab();});button.addEventListener('keydown',event=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();const keys=Object.keys(panels),index=keys.indexOf(key);state.detailTab=event.key==='Home'?keys[0]:event.key==='End'?keys[keys.length-1]:keys[(index+(event.key==='ArrowRight'?1:-1)+keys.length)%keys.length];showDetailTab();$(`detail-tab-${state.detailTab}`).focus();});nav.append(button);}
  panels.overview.append(facts);if(map)panels.overview.append(map);if(mapLink)panels.overview.append(mapLink);
  for(const paragraph of [...body.children].filter(node=>node.tagName==='P'))panels.overview.append(paragraph);
  panels.verification.append(verification);panels.dispatch.append(actions,staff);if(progress)panels.dispatch.append(progress);if(responseSection)panels.dispatch.append(responseSection);panels.activity.append(activity);
  const shared=document.createElement('div');shared.className='shared-note';shared.append(noteLabel,note);
  header.after(shared,nav,...Object.values(panels));showDetailTab();
}
function showDetailTab(){for(const key of ['overview','verification','dispatch','activity']){const active=state.detailTab===key,button=$(`detail-tab-${key}`),panel=$(`detail-panel-${key}`);button.setAttribute('aria-selected',String(active));button.tabIndex=active?0:-1;panel.hidden=!active;}}
async function loadEvents(id) { try { const events=await api(`/medical-alerts/${id}/events`); if(state.selected!==id)return; $('event-list').innerHTML=events.length?events.map(e=>`<li><strong>${escapeHtml(friendly(e.action))}</strong>${e.note?` · ${escapeHtml(e.note)}`:''}<small>${e.actor_id!=null?`${e.action==='created'?'Reporter':'Admin'} #${escapeHtml(e.actor_id)} · `:''}${escapeHtml(new Date(e.created_at).toLocaleString())}</small></li>`).join(''):'<li>No activity yet.</li>'; } catch(e){toast(e.message,true);} }
async function loadAdminMessages(id) { try {const messages=await api(`/medical-alerts/${id}/messages`);if(state.selected===id)renderMessages('admin-messages',messages);}catch(e){toast(e.message,true);} }
async function loadSuggestions(placeId,id) { if(!placeId)return; try {const rows=await api(`/campus/coverage/${placeId}`);if(state.selected!==id)return;$('staff-suggestions').textContent=rows.length?`Suggested: ${rows.map(r=>`${r.name}${r.on_duty?' (on duty)':' (off duty)'}`).join(', ')}`:'No coverage configured for this place. Choose a contact manually.';}catch(e){$('staff-suggestions').textContent='Could not load coverage.';} }

async function adminAction(action) {
  if(!state.selected)return; const alertId=state.selected; const note=$('action-note')?.value.trim()||'';
  const alert=state.alerts.find(a=>a.id===alertId); const version=alert?.version;
  const body={note,version};
  const needsNote=!['claim','demo-progress'].includes(action)||(action==='demo-progress'&&alert?.status==='arrived');
  if(needsNote && note.length<(action==='close-false'?10:2)) {toast('Write a clear action note first.',true);$('action-note').focus();return;}
  try {await api(`/medical-alerts/${alertId}/${action}`,{method:'POST',json:action==='claim'?{version}:body});if(action!=='claim'&&action!=='demo-progress'&&state.actionDrafts[alertId]?.trim()===note)delete state.actionDrafts[alertId];toast('Action recorded.');await refreshAdmin();}
  catch(e){toast(userMessage(e),true);if(e.status===409)await refreshAdmin();}
}
async function saveVerification(){const alertId=state.selected,note=$('action-note').value.trim(),alert=state.alerts.find(a=>a.id===alertId);if(note.length<2){toast('Add verification notes first.',true);$('action-note').focus();return;}try{await api(`/medical-alerts/${alertId}/verification`,{method:'POST',json:{version:alert.version,verification:$('verification-choice').value,note}});if(state.actionDrafts[alertId]?.trim()===note)delete state.actionDrafts[alertId];toast('Verification saved.');await refreshAdmin();}catch(e){toast(userMessage(e),true);if(e.status===409)await refreshAdmin();}}
async function sendStaffAlert() { const staffId=Number($('staff-choice').value);const version=state.alerts.find(a=>a.id===state.selected)?.version;if(!staffId){toast('Choose a demo contact.',true);return;}try{await api(`/medical-alerts/${state.selected}/staff`,{method:'POST',json:{staff_id:staffId,version,method:$('demo-contact-method').value}});toast('Demo contact attempt recorded. No message or call was sent.');refreshAdmin();}catch(e){toast(userMessage(e),true);} }
async function runAutomaticDemo(){
  const alertId=state.selected, staffId=Number($('staff-choice').value), method=$('demo-contact-method').value;
  if(state.autoDemoRunning)return;
  if(!staffId){toast('Choose a demo contact first.',true);return;}
  state.autoDemoRunning=true;
  const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
  const current=async()=>{const row=(await api('/medical-alerts/admin/queue')).find(a=>a.id===alertId);if(!row)throw Error('Demo alert is no longer available');return row;};
  try{
    let alert=await current();
    if(!['new','acknowledged','checking'].includes(alert.status))throw Error('Demo alert is no longer awaiting review');
    if(alert.status==='new'){alert=await api(`/medical-alerts/${alertId}/claim`,{method:'POST',json:{version:alert.version}});await refreshAdmin();await pause(1200);}
    alert=await api(`/medical-alerts/${alertId}/verify`,{method:'POST',json:{version:alert.version,note:'DEMO presentation: fictional verification recorded by admin.'}});
    await refreshAdmin();await pause(1200);
    alert=(await api(`/medical-alerts/${alertId}/staff`,{method:'POST',json:{version:alert.version,staff_id:staffId,method}})).alert;
    await refreshAdmin();
    const deadline=Date.now()+305000;
    while(alert.status==='contact_pending'&&Date.now()<deadline){await pause(1000);alert=await current();}
    if(alert.status!=='staff_alerted')throw Error('Demo contact did not accept; choose another contact manually.');
    await pause(1200);
    alert=await api(`/medical-alerts/${alertId}/dispatch-medical`,{method:'POST',json:{version:alert.version,note:'DEMO presentation: fictional team dispatch.'}});
    await refreshAdmin();
    for(const expected of ['en_route','arrived','resolved']){await pause(1500);alert=await api(`/medical-alerts/${alertId}/demo-progress`,{method:'POST',json:{version:alert.version,note:'Automatic DEMO presentation; no real response.'}});if(alert.status!==expected)throw Error('Demo progress changed unexpectedly');await refreshAdmin();}
    toast('Automatic demo completed. No real services were contacted.');
  }catch(error){toast(error.message||'Automatic demo stopped. Continue manually.',true);await refreshAdmin();}
  finally{state.autoDemoRunning=false;if(state.selected===alertId)await selectAlert(alertId);}
}
async function recordStaffResponse(kind) { const version=state.alerts.find(a=>a.id===state.selected)?.version; const note=kind==='staff-findings'?`DEMO: ${$('staff-findings').value.trim()}`:'DEMO acknowledgement simulated by admin. No contact occurred.'; if(kind==='staff-findings'&&note.length<8){toast('Enter demo findings first.',true);$('staff-findings').focus();return;} try { await api(`/medical-alerts/${state.selected}/${kind}`,{method:'POST',json:{version,note}}); toast('Demo response recorded.'); await loadEvents(state.selected); } catch(e) { toast(userMessage(e),true); } }
async function sendAdminMessage(e) {e.preventDefault();const body=$('admin-message').value.trim();if(!body)return;try{await api(`/medical-alerts/${state.selected}/messages`,{method:'POST',json:{body}});$('admin-message').value='';loadAdminMessages(state.selected);}catch(err){toast(err.message,true);} }

function renderContacts() {
  const snapshot=JSON.stringify(state.contacts);
  if(snapshot===state.contactsSnapshot)return;
  state.contactsSnapshot=snapshot;
  $('contact-list').innerHTML=state.contacts.length?state.contacts.map(c=>`<div class="contact-item"><strong>${escapeHtml(c.name)}</strong><small>${friendly(c.kind)} · ${friendly(c.shift)} · ${c.active?'available':'unavailable'}</small><small>${escapeHtml(c.phone||'DEMO')} · fictional demo identifier</small><details><summary>Edit demo contact</summary><form class="contact-edit" data-contact-id="${c.id}"><label>Shift<select name="shift"><option value="all" ${c.shift==='all'?'selected':''}>All hours</option><option value="day" ${c.shift==='day'?'selected':''}>Day</option><option value="night" ${c.shift==='night'?'selected':''}>Night</option></select></label><label>Simulated outcome<select name="outcome"><option value="accepted" ${(!c.outcome||c.outcome==='accepted')?'selected':''}>Accepted</option><option value="no_answer" ${c.outcome==='no_answer'?'selected':''}>No answer</option><option value="unavailable" ${c.outcome==='unavailable'?'selected':''}>Unavailable</option></select></label><label class="contact-active"><input type="checkbox" name="active" ${c.active?'checked':''}> Available for simulation</label><button class="button button-navy" type="submit">Save contact</button></form></details></div>`).join(''):'<p class="muted">Add a demo contact to start a simulation.</p>';
  $('contact-list').querySelectorAll('.contact-edit').forEach(form=>{const contact=state.contacts.find(c=>c.id===Number(form.dataset.contactId));const label=document.createElement('label');label.textContent='Response delay (seconds)';const input=document.createElement('input');input.type='number';input.name='delay_seconds';input.min='0';input.max='300';input.value=String(contact?.delay_seconds||0);label.append(input);form.querySelector('button').before(label);form.addEventListener('submit',updateContact);});
  $('coverage-staff').innerHTML='<option value="">Choose contact</option>'+state.contacts.map(c=>`<option value="${c.id}">${escapeHtml(c.name)}</option>`).join('');
}
function renderContactAssignments() {
  document.querySelectorAll('#contact-list .contact-edit').forEach(form=>{
    const id=Number(form.dataset.contactId);
    let label=form.closest('.contact-item').querySelector('.contact-assignment');
    if(!label){label=document.createElement('small');label.className='contact-assignment';form.closest('details').before(label);}
    const assignments=state.alerts.filter(a=>Number(a.contact_id)===id && ['contact_pending','staff_alerted','medical_dispatched','en_route','arrived'].includes(a.status));
    label.textContent=assignments.length ? assignments.map(a=>`Demo #${a.id}: ${friendly(a.status)}`).join(' · ') : 'No active assignment in the displayed queue';
  });
}
async function createContact(e){e.preventDefault();const body={name:$('contact-name').value.trim(),kind:$('contact-kind').value,shift:$('contact-shift').value};try{await api('/campus/contacts',{method:'POST',json:body});$('contact-form').reset();toast('Demo contact added.');refreshAdmin();}catch(err){toast(userMessage(err),true);} }
async function updateContact(e){e.preventDefault();const form=e.currentTarget;const body={shift:form.elements.shift.value,outcome:form.elements.outcome.value,delay_seconds:Number(form.elements.delay_seconds.value),active:form.elements.active.checked};try{await api(`/campus/contacts/${form.dataset.contactId}`,{method:'PATCH',json:body});toast('Demo contact updated.');refreshAdmin();}catch(err){toast(err.message,true);} }
async function saveCoverage(e){e.preventDefault();const body={place_id:Number($('coverage-place').value),staff_id:Number($('coverage-staff').value),rank:Number($('coverage-rank').value)};if(!body.place_id||!body.staff_id){toast('Choose a place and contact.',true);return;}try{await api('/campus/coverage',{method:'POST',json:body});toast('Coverage saved.');if(state.selected)selectAlert(state.selected);}catch(err){toast(err.message,true);} }

async function refreshStaff(){try{const alerts=await api('/medical-alerts/staff/inbox');const snapshot=JSON.stringify(alerts);if(snapshot===state.staffSnapshot)return;state.staffSnapshot=snapshot;$('staff-inbox').innerHTML=alerts.length?alerts.map(a=>`<article class="panel staff-card"><h2>Medical alert #${a.id}</h2><p>${escapeHtml(placeName(a.place_id))}${a.location_text?' · '+escapeHtml(a.location_text):''}</p><p><span class="status-tag ${escapeHtml(a.status)}">${friendly(a.status)}</span></p><button class="button button-navy" data-ack="${a.id}" ${a.assignment_status==='acknowledged'?'disabled':''}>${a.assignment_status==='acknowledged'?'Acknowledged':'Acknowledge'}</button><label for="finding-${a.id}" class="sr-only">Findings for alert ${a.id}</label><textarea id="finding-${a.id}" rows="2" placeholder="What did you find at the scene?"></textarea><button class="button button-soft" data-findings="${a.id}">Send findings</button></article>`).join(''):'<div class="panel empty-list">No alerts assigned to you.</div>';$('staff-inbox').querySelectorAll('[data-ack]').forEach(b=>b.addEventListener('click',async()=>{try{await api(`/medical-alerts/${b.dataset.ack}/staff/acknowledge`,{method:'POST'});b.disabled=true;b.textContent='Acknowledged';toast('Acknowledgement sent.');}catch(e){toast(e.message,true);}}));$('staff-inbox').querySelectorAll('[data-findings]').forEach(b=>b.addEventListener('click',async()=>{const body=$('finding-'+b.dataset.findings).value.trim();if(body.length<2){toast('Enter your findings first.',true);return;}try{await api(`/medical-alerts/${b.dataset.findings}/staff/findings`,{method:'POST',json:{findings:body}});toast('Findings sent to admin.');}catch(e){toast(e.message,true);}}));}catch(e){toast(e.message,true);} }

function openAuth(){ setAuthMode('login');$('auth-form').reset();$('auth-dialog').showModal();$('auth-email').focus(); }
function setAuthMode(mode){state.authMode=mode;const register=mode==='register';$('auth-title').textContent=register?'Create student account':'Sign in';$('register-name-wrap').classList.toggle('hidden',!register);$('auth-submit').textContent=register?'Create account':'Sign in';$('auth-switch').textContent=register?'Already have an account? Sign in':'Create a student account';$('auth-error').classList.add('hidden');}
async function handleAuth(e){e.preventDefault();const email=$('auth-email').value.trim();const password=$('auth-password').value;const error=$('auth-error');error.classList.add('hidden');if(!state.demoReady){error.textContent='The isolated demo service is unavailable.';error.classList.remove('hidden');return;}try{if(state.authMode==='register'){await api('/auth/register',{method:'POST',json:{name:$('auth-name').value.trim(),email,password}});}const form=new URLSearchParams({username:email,password});const result=await api('/auth/login',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:form});state.token=result.access_token;localStorage.setItem('cer_token',state.token);state.user=await api('/auth/me');$('auth-dialog').close();showView();toast(`Signed in as ${state.user.name}.`);}catch(err){error.textContent=err.message;error.classList.remove('hidden');} }
async function restoreSession(){if(!state.token)return;try{state.user=await api('/auth/me');}catch(e){if(e.status===401||e.status===403){state.token=null;localStorage.removeItem('cer_token');}else $('service-status').textContent='Could not restore your session. The demo will retry automatically.';}}

async function connectDemoService(){
  if(state.connecting || state.demoReady)return;
  state.connecting=true;
  try {
    if(window.CER_CONFIG?.isApiConfigured && !window.CER_CONFIG.isApiConfigured())throw new Error('Demo service is not configured.');
    const [places,config]=await Promise.all([api('/medical-alerts/places'),api('/medical-alerts/config')]);
    if(config.demo_mode!==true)throw new Error('The connected service is not the isolated demo.');
    state.demoReady=true;state.places=places;
    $('place').innerHTML='<option value="">Choose a building or hostel</option>'+places.map(p=>`<option value="${escapeHtml(p.name)}">${escapeHtml(p.name)}</option>`).join('');
    $('coverage-place').innerHTML='<option value="">Choose place</option>'+places.map(p=>`<option value="${p.id}">${escapeHtml(p.name)}</option>`).join('');
    $('help-button').disabled=false;$('bystander-button').disabled=false;
    $('service-status').textContent='Demo service connected. No real responders will be contacted.';
    await restoreSession();showView();
  } catch(e) {
    $('service-status').textContent=`Demo unavailable: ${e.message} Retrying automatically. For a real emergency, call emergency services directly.`;
  } finally {state.connecting=false;}
}

async function init(){
  $('directory-title').textContent='Demo contacts'; $('contact-form').querySelector('h3').textContent='Add demo contact'; $('contact-phone').previousElementSibling.remove(); $('contact-phone').remove();
  document.querySelectorAll('.step-grid p')[1].textContent='An admin reviews the demo request and can simulate a contact.'; document.querySelectorAll('.step-grid p')[2].textContent='The dashboard simulates dispatch and team progress. No real services are contacted.';
  $('help-button').addEventListener('click',()=>startAlert('self'));
  $('bystander-button').addEventListener('click',()=>startAlert('bystander'));
  $('details-form').addEventListener('submit',saveDetails);
  $('details-form').addEventListener('input',()=>{state.detailsDirty=true;$('details-feedback').textContent='Unsaved changes.';});
  $('share-location').addEventListener('click',requestDeviceLocation);
  if ($('student-message-form')) $('student-message-form').addEventListener('submit',sendStudentMessage);
  $('login-open').addEventListener('click',openAuth);
  $('auth-close').addEventListener('click',()=>$('auth-dialog').close());
  $('auth-switch').addEventListener('click',()=>setAuthMode(state.authMode==='login'?'register':'login'));
  $('auth-form').addEventListener('submit',handleAuth);
  $('logout').addEventListener('click',()=>{state.token=null;state.user=null;localStorage.removeItem('cer_token');showView();toast('Signed out.');});
  $('contact-form').addEventListener('submit',createContact);
  $('coverage-form').addEventListener('submit',saveCoverage);
  $('queue-search').addEventListener('input',()=>renderQueue(true)); $('queue-filter').addEventListener('change',()=>renderQueue(true));
  $('reset-demo').addEventListener('click',async()=>{if(!window.confirm('Clear all demo alerts and their activity? Demo contacts and other records will be kept.'))return;try{const result=await api('/demo/reset',{method:'POST'});state.selected=null;state.selectedSnapshot=null;state.queueSnapshot=null;$('admin-detail').classList.add('empty-detail');$('admin-detail').textContent='Select an alert to review it.';$('detail-id').textContent='';toast(result.message);await refreshAdmin();}catch(e){toast(userMessage(e),true);}});
  await connectDemoService();showView();
  state.timer=setInterval(()=>{if(!state.demoReady){connectDemoService();return;}if(state.token&&!state.user){restoreSession().then(showView);return;}if(state.user?.role==='admin')refreshAdmin();else if(state.active)refreshStudent();},15000);
  window.addEventListener('online',()=>{if(!state.demoReady)connectDemoService();else if(state.user?.role==='admin')refreshAdmin();else if(state.active)refreshStudent();});
}
document.addEventListener('DOMContentLoaded',init);

