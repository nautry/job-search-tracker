/** @OnlyCurrentDoc */
/* Bound to your tracker: Extensions > Apps Script. No credentials in source. */
const HEADERS = ['Status','Applied date','Follow-up','Notes','Company','Job title','Location','Role fit','Location fit','Priority','Experience','Salary','Flags','Why match','Link','Job ID','Availability','First seen','Last seen','Source','Employer posted','Posting age (days)','Recency points','Recommendation','May 2027 eligibility','Fit reason','Availability state','Active confirmed','Verification detail','Related posting IDs','Duplicate review','Resume variant','Verified at','Queue eligible','Deferred until'];
const STATUSES = ['Not Applied','Applied','Interviewing','Offer','Rejected','Not Interested','Withdrawn'];
const QUEUE_HEADERS = ['Assignment','Recommendation','Company','Job / employer link','Location','Priority','Employer posted','Experience / May 2027 eligibility','Availability / duplicate check','Resume','Reason / next check','Record'];
const SCRIPT_VERSION = '2026-11-19-practical-v3';
const DECISIONS = ['Recommended','Stretch','Hold','Closed','Duplicate','Ineligible'];
const SOURCE_HEADERS = ['Company','Status','Collected','Matched','Checked at','Scope','Error','Careers URL','Context'];

function onOpen() {
  SpreadsheetApp.getUi().createMenu('Job search').addItem('Refresh jobs','syncJobs').addItem('Refresh dashboard / refill','refreshViews').addItem('Show up to five recommendations','showFiveRecommendations').addItem('Set up daily refresh','installDailyTrigger').addToUi();
}

function onEdit(e) {
  if (!e || e.range.getSheet().getName() !== 'Jobs' || (e.range.getColumn() > 4 && e.range.getColumn() !== 35) || e.range.getLastRow() < 2) return;
  const lock = LockService.getDocumentLock();
  if (!lock.tryLock(500)) return;
  try { refreshViews({skipVerification:true}); } finally { lock.releaseLock(); }
}

function textCell(value) {
  if (typeof value === 'number' || value instanceof Date) return value;
  const s = value == null ? '' : String(value);
  return /^[=+@\-]/.test(s) ? "'" + s : s;
}

function fitSummary(j){
  const terms=j.screening_evidence?.hardware_terms||[];
  const text=terms.length?'Matches '+terms.slice(0,5).join(', '):j.fit_reason||j.decision_reason||'Automatic screening pending';
  return text.length<=145?text:text.slice(0,142).replace(/\s+\S*$/,'')+'…';
}

function autoFields(j) {
  if (!/^https:\/\//i.test(j.url)) throw new Error('Invalid job link: ' + j.id);
  const title = String(j.title).replace(/"/g,'""');
  const url = String(j.url).replace(/"/g,'""');
  return [textCell(j.company), '=HYPERLINK("'+url+'","'+title+'")', textCell(j.location), Number(j.role_score), textCell(j.location_fit), Number(j.priority), textCell(j.experience), textCell(j.salary), textCell(j.flags), textCell(j.evidence), j.url, textCell(j.id), textCell(j.availability), j.first_seen ? new Date(j.first_seen) : '', j.last_seen ? new Date(j.last_seen) : '', textCell(j.source),
    postingDate(j.posted_at), j.posting_age ?? 'Unknown', Number(j.recency_points || 0),
    DECISIONS.includes(j.category) ? j.category : 'Hold',
    textCell([j.start_eligibility || 'Timing not stated',...(j.caveats||[]).filter(c=>!c.includes('timing')&&!c.includes('start date'))].join(' | ').slice(0,200)),
    textCell(fitSummary(j)), textCell(j.availability_state || 'Unverified'), postingDate(j.last_confirmed_active), textCell(j.verification_detail || 'Employer URL not verified'), textCell((j.related_ids || []).join(' | ')), textCell(j.duplicate_state || ''), textCell(j.resume_variant || 'Design'), postingDate(j.availability_checked_at), j.queue_eligible === true];
}

function postingDate(value) {
  const ms = Date.parse(value || '');
  return Number.isFinite(ms) && ms <= Date.now() ? new Date(ms) : '';
}

function validateFeed(feed) {
  if (feed.schema_version !== 1 || !Array.isArray(feed.jobs) || !Array.isArray(feed.source_status) || !Number.isFinite(Date.parse(feed.generated_at))) throw new Error('Feed schema is invalid');
  const ids = new Set();
  feed.jobs.forEach(j => {
    if (!j.id || ids.has(j.id) || !j.title || !/^https:\/\//.test(j.url) || !Number.isFinite(j.role_score) || !Number.isFinite(j.priority)) throw new Error('Invalid or duplicate job: '+j.id);
    ids.add(j.id);
  });
  if (feed.jobs.length > 20000) throw new Error('Feed exceeds supported 20,000 jobs');
}

function indexRows(rows) {
  const index = new Map();
  rows.forEach((r,i) => {
    const id = String(r[15] || '');
    if (id && index.has(id)) throw new Error('Duplicate Sheet job ID: '+id+'. Resolve before sync.');
    if (id) index.set(id,i+2);
  });
  return index;
}

function syncJobs() {
  const lock = LockService.getDocumentLock();
  lock.waitLock(30000);
  try {
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    if(ss.setSpreadsheetTimeZone)ss.setSpreadsheetTimeZone('America/Indianapolis');
    const cfg = ss.getSheetByName('Settings');
    const feedUrl = String(cfg.getRange('B2').getValue()).trim();
    if (!/^https:\/\/raw\.githubusercontent\.com\//.test(feedUrl)) throw new Error('Set Settings!B2 to your raw GitHub data/jobs.json URL.');
    const response = UrlFetchApp.fetch(feedUrl,{muteHttpExceptions:true});
    if (response.getResponseCode() !== 200) throw new Error('Feed HTTP '+response.getResponseCode()+'. Existing jobs were preserved.');
    const feed = JSON.parse(response.getContentText());
    validateFeed(feed);
    const maxAge = Number(feed.preferences && feed.preferences.stale_after_hours) || 36;
    if (Date.now()-Date.parse(feed.generated_at)>maxAge*3600000) throw new Error('Feed is stale. Run the GitHub collector first. Existing jobs were preserved.');
    const sh = ss.getSheetByName('Jobs');
    if (sh.getMaxColumns() < HEADERS.length) sh.insertColumnsAfter(sh.getMaxColumns(), HEADERS.length-sh.getMaxColumns());
    const existing = sh.getRange(1, 1, 1, HEADERS.length).getValues()[0];
    if (existing.some((value, i) => i < 20 ? value !== HEADERS[i] : value && value !== HEADERS[i])) {
      throw new Error('Unexpected Jobs headers. Restore the expected headers before sync.');
    }
    sh.getRange(1, 21, 1, HEADERS.length - 20).setValues([HEADERS.slice(20)]);
    const lastExisting = sh.getLastRow();
    const rows = lastExisting > 1 ? sh.getRange(2, 1, lastExisting - 1, HEADERS.length).getValues() : [];
    const index = indexRows(rows);
    const newJobs = feed.jobs.filter(j => !index.has(j.id));
    const last = Math.max(2, lastExisting + newJobs.length);
    if (last > sh.getMaxRows()) sh.insertRowsAfter(sh.getMaxRows(), last - sh.getMaxRows());
    const byId = new Map(feed.jobs.map(j => [j.id, j]));
    const states = new Map(feed.source_status.map(source => [source.source, source.status]));

    // Batch contiguous automated writes. Keep historical first-seen and all A:D values.
    let start = 0;
    let batch = [];
    const flush = () => {
      if (batch.length) sh.getRange(start, 5, batch.length, HEADERS.length - 5).setValues(batch);
      batch = [];
    };
    rows.forEach((row, i) => {
      const j = byId.get(String(row[15]));
      if (!j) {
        flush();
        if (row[15]) {
          sh.getRange(i + 2, 17).setValue(states.get(String(row[19])) === 'ok'
            ? 'Not seen in latest complete search' : 'Source incomplete / unavailable; retained');
          sh.getRange(i + 2, 24).setValue('Hold');
        }
        return;
      }
      if (!batch.length) start = i + 2;
      const fields = autoFields(j);
      if (row[17] !== '') fields[13] = row[17];
      batch.push(fields);
    });
    flush();
    if (newJobs.length) {
      sh.getRange(lastExisting + 1, 1, newJobs.length, HEADERS.length)
        .setValues(newJobs.map(j => ['Not Applied', '', '', '', ...autoFields(j), '']));
    }
    sh.getRange(2,35,last-1,1).setNumberFormat('mm/dd/yy');
    sh.getRange(2,28,last-1,1).setNumberFormat('mmm d, yyyy hh:mm');
    sh.getRange(2,33,last-1,1).setNumberFormat('mmm d, yyyy hh:mm');
    sh.getRange(2,1,last-1,1).setDataValidation(SpreadsheetApp.newDataValidation().requireValueInList(STATUSES,true).setAllowInvalid(false).build());
    sh.getRange(2,2,last-1,2).setNumberFormat('mm/dd/yy');
    sh.getRange(2,18,last-1,2).setNumberFormat('mm/dd/yy');
    sh.getRange(2,21,last-1,1).setNumberFormat('mmm d, yyyy');
    const values = feed.source_status.map(s=>[s.company,s.status,s.collected,s.matched,new Date(s.checked_at),s.scope,s.error || '',s.careers_url,s.context]);
    writeSourceStatus(ss, values);
    cfg.getRange('B3').setValue(new Date(feed.generated_at));
    cfg.getRange('B4').setValue(new Date());


    cfg.getRange('B5').setValue('Sync succeeded; '+feed.jobs.length+' feed jobs; '+feed.source_status.filter(s=>s.status!=='ok').length+' sources need review');
    PropertiesService.getDocumentProperties().setProperty('shortlistLimit', String(Number(feed.preferences && feed.preferences.shortlist_limit)||12));
    PropertiesService.getDocumentProperties().setProperty('shortlistPerCompany', String(Number(feed.preferences && feed.preferences.shortlist_per_company)||2));
    PropertiesService.getDocumentProperties().setProperty('defenseTarget', String(Number(feed.preferences && feed.preferences.defense_target)||0.725));
    saveChunks(PropertiesService.getDocumentProperties(),'defenseIds',feed.jobs.filter(j=>j.defense).map(j=>j.id));
    saveChunks(PropertiesService.getDocumentProperties(),'verificationHints',feed.jobs.filter(j=>j.queue_eligible).map(j=>({id:j.id,url:j.url,provider_job_id:j.provider_job_id,detail_api:j.detail_api,qualification_category:j.qualification_category,decision_reason:j.decision_reason})));
    PropertiesService.getDocumentProperties().setProperty('priorityQueueLimit', String(feed.preferences?.priority_queue_limit || 24));
    PropertiesService.getDocumentProperties().setProperty('dailyTarget', String(feed.preferences?.daily_target || 3));
    refreshViews();
    cfg.getRange('B25').setValue('Bound script '+SCRIPT_VERSION+'; successful sync '+new Date().toISOString());
    cfg.getRange('B28').setValue('Practical screening active; existing syncJobs trigger retained.');
  } catch(e) {
    SpreadsheetApp.getActiveSpreadsheet().getSheetByName('Settings').getRange('B5').setValue('Sync failed: '+e.message);
    throw e;
  } finally { lock.releaseLock(); }
}

function writeSourceStatus(ss, values) {
  let sh=ss.getSheetByName('Sources');
  if(!sh){sh=ss.insertSheet('Sources');sh.getRange(1,1,1,9).setValues([SOURCE_HEADERS]);}
  // Typed Sheets columns reject clearContent/setNumberFormat. Values-only writes
  // avoid the archive-on-every-sync loop; retain existing native table and history.
  const previous=sh.getLastRow();
  if(values.length)sh.getRange(2,1,values.length,9).setValues(values.map(r=>r.map(textCell)));
  if(previous>values.length+1)sh.getRange(values.length+2,1,previous-values.length-1,9).setValues(Array.from({length:previous-values.length-1},()=>Array(9).fill('')));
  if(sh.setFrozenRows)sh.setFrozenRows(1);
}

function saveChunks(props,key,values){
  // Keep each property well below the Apps Script 9 KB per-value limit.
  const chunks=[];let current=[];
  for(const value of values){const next=[...current,value];if(JSON.stringify(next).length>3000&&current.length){chunks.push(current);current=[value];}else current=next;}
  if(current.length)chunks.push(current);
  chunks.forEach((v,i)=>props.setProperty(key+i,JSON.stringify(v)));
  props.setProperty(key+'Count',String(chunks.length));
}
function loadChunks(props,key){const n=Number(props.getProperty(key+'Count'));if(!Number.isFinite(n)||n===0)return [];
  return Array.from({length:n},(_,i)=>JSON.parse(props.getProperty(key+i)||'[]')).flat();}

function localDay(value=new Date()){
  if(typeof Utilities!=='undefined'&&Utilities.formatDate)return Utilities.formatDate(value,'America/Indianapolis','yyyy-MM-dd');
  const parts=new Intl.DateTimeFormat('en-US',{timeZone:'America/Indianapolis',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(value);
  const d=Object.fromEntries(parts.map(p=>[p.type,p.value]));return d.year+'-'+d.month+'-'+d.day;
}
function calendarDate(value){
  if(value instanceof Date)return Number.isFinite(value.getTime())?localDay(value):'';
  if(typeof value==='number')return new Date((Math.floor(value)-25569)*86400000).toISOString().slice(0,10);
  const text=String(value||'');if(/^\d{4}-\d{2}-\d{2}$/.test(text))return text;
  const m=text.match(/^(\d{1,2})\/(\d{1,2})\/(\d{2}|\d{4})$/);
  if(m)return String(m[3].length===2?'20'+m[3]:m[3])+'-'+m[1].padStart(2,'0')+'-'+m[2].padStart(2,'0');
  return '';
}
function submittedToday(rows,now=new Date()){const day=localDay(now);return rows.filter(r=>['Applied','Interviewing','Offer','Rejected','Withdrawn'].includes(r[0])&&calendarDate(r[1])===day).length;}

function verifyHint(hint){
  const [provider,slug,raw]=hint.id.split(':');const req=hint.provider_job_id||raw;
  function get(url){const r=UrlFetchApp.fetch(url,{muteHttpExceptions:true});return {code:r.getResponseCode(),text:r.getContentText()};}
  let detail,signal='',url=hint.url;
  try{
    if(provider==='greenhouse'){
      const r=get('https://boards-api.greenhouse.io/v1/boards/'+slug+'/jobs/'+req+'?questions=true');
      if([404,410].includes(r.code))return {state:'Confirmed closed',reason:'Official ATS detail HTTP '+r.code};
      if(r.code!==200)return {state:'Unverified',reason:'ATS check HTTP '+r.code};
      detail=JSON.parse(r.text);if(String(detail.id)!==String(req))return {state:'Unverified',reason:'ATS identity mismatch'};
      if(detail.application_deadline&&Date.parse(detail.application_deadline)<Date.now())return {state:'Confirmed closed',reason:'Employer application deadline passed'};
      if((detail.questions||[]).some(q=>(q.fields||[]).length))signal='Official ATS publishes application fields';
      url=detail.absolute_url||url;
    }else if(provider==='workday'&&hint.detail_api){
      const r=get(hint.detail_api);if([404,410].includes(r.code))return {state:'Confirmed closed',reason:'Official ATS detail HTTP '+r.code};
      if(r.code!==200)return {state:'Unverified',reason:'ATS check HTTP '+r.code};detail=JSON.parse(r.text).jobPostingInfo||{};
      if(detail.canApply===false)return {state:'Confirmed closed',reason:'Workday canApply=false'};
      if(detail.canApply===true)signal='Workday canApply=true';
    }else if(provider==='lever'){
      const r=get('https://api.lever.co/v0/postings/'+slug+'/'+req);if([404,410].includes(r.code))return {state:'Confirmed closed',reason:'Official ATS detail HTTP '+r.code};
      if(r.code!==200)return {state:'Unverified',reason:'ATS check HTTP '+r.code};detail=JSON.parse(r.text);url=detail.applyUrl||url;
    }else return {state:'Unverified',reason:'Collector recheck pending; application form evidence remains inconclusive'};
    if(!/^https:\/\//.test(url))return {state:'Unverified',reason:'HTTPS employer application URL unavailable'};
    const page=get(url);if(page.code!==200)return {state:'Unverified',reason:'Application URL check HTTP '+page.code};
    if(/this (?:job|position|posting|role) (?:is |has been )?(?:no longer available|no longer accepting applications|closed|removed|filled|expired)/i.test(page.text))return {state:'Confirmed closed',reason:'Employer page explicitly states closure'};
    if(/<form\b/i.test(page.text)&&/<(?:input|textarea)\b/i.test(page.text)&&/resume|candidate|email/i.test(page.text)&&/type=["']submit|submit.{0,30}application/i.test(page.text))signal=signal||'Public application form and applicant fields are available';
    return signal?{state:'Verified active',reason:signal+'; no submission attempted; interview activity unknown'}:{state:'Unverified',reason:'Listing accessible; application-enabled state unconfirmed'};
  }catch(e){return {state:'Unverified',reason:'Automatic verification unavailable: '+String(e.message).slice(0,120)};}
}

function verifyUnapplied(ss,rows,hints,budget=8,now=new Date()){
  const byId=new Map(hints.map(h=>[h.id,h]));const sh=ss.getSheetByName('Jobs');
  const candidates=rows.map((r,i)=>({r,i,h:byId.get(String(r[15]))})).filter(o=>o.h&&o.h.qualification_category==='Recommended'&&o.r[0]==='Not Applied'&&!deferred(o.r,now)&&!o.r[29]&&o.r[23]!=='Ineligible'&&o.r[23]!=='Closed'&&(o.r[26]!=='Verified active'||ageHours(o.r[27],now)>24))
    .sort((a,b)=>b.r[9]-a.r[9]).slice(0,budget);
  for(const {r,i,h} of candidates){const checked=verifyHint(h);r[26]=checked.state;r[28]=checked.reason;r[32]=now;
    if(checked.state==='Verified active'){r[27]=now;r[23]='Recommended';}else r[23]=checked.state==='Confirmed closed'?'Closed':'Hold';
    for(const c of [23,26,27,28,32])sh.getRange(i+2,c+1).setValue(textCell(r[c]));
  }
  return candidates.length;
}

function ageHours(value, now=new Date()) {
  const t = value instanceof Date ? value.getTime() : Date.parse(value || '');
  return Number.isFinite(t) ? (now.getTime()-t)/3600000 : Infinity;
}

function deferred(row, now) {
  const d = row[34] instanceof Date ? row[34] : new Date(row[34] || '');
  return Number.isFinite(d.getTime()) && d.getTime() >= new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
}

function ready(row, now=new Date(), appliedIds=new Set()) {
  const related = String(row[29] || '').split(' | ');
  return !/manufacturing|production|process|industrial|tooling|factory automation|supplier development|welding|sourcing|procurement|construction|HVAC|technician|field service/i.test(row[5]) && row[0] === 'Not Applied' && row[33] === true && Number(row[9]) >= 55 && row[23] === 'Recommended' && row[26] === 'Verified active' &&
    ageHours(row[27], now) <= 72 && ageHours(row[27], now) >= -1  &&
    !/Deprioritized|Location review/.test(row[8]) && !deferred(row, now) &&
    !related.some(id => appliedIds.has(id)) && !/Possible repost|Exact requisition alias/.test(row[30]);
}

function queueCandidates(rows, now=new Date()) {
  return rows.filter(r => r[15] && r[0] === 'Not Applied' && r[33] === true &&
    ['Recommended','Stretch','Hold'].includes(r[23]) && (r[16] === 'Seen in latest search' || r[26] === 'Verified active' && ageHours(r[27],now)<=72) && r[26] !== 'Confirmed closed' && !/manufacturing|production|process|industrial|tooling|factory automation|supplier development|welding|sourcing|procurement|construction|HVAC|technician|field service/i.test(r[5]) && !deferred(r, now) && !/Deprioritized|Location review/.test(r[8]) &&
    Number(r[9]) >= 55).sort((a,b) => {
      const rank = r => ready(r, now) ? 0 : r[23] === 'Hold' && (/entry.level|new.grad|early.career|engineer i\b/i.test(r[5]) || /^(0|1)\+/.test(r[10])) ? 1 : r[23] === 'Stretch' ? 2 : 3;
      return rank(a)-rank(b) || b[9]-a[9] || String(a[15]).localeCompare(String(b[15]));
    });
}

function shortlist(rows, limit=5, perCompany=2, defenseIds=new Set(), defenseTarget=.725, now=new Date()) {
  const applied = new Set(rows.filter(r => r[0] !== 'Not Applied').map(r => String(r[15])));
  const candidates = rows.filter(r => ready(r, now, applied)).sort((a,b) => b[9]-a[9] || String(a[15]).localeCompare(String(b[15])));
  const selected=[], counts=new Map();
  const add=r => {const company=String(r[4]).toLowerCase();const n=counts.get(company)||0;
    if(selected.length>=Math.min(5,limit)||selected.includes(r)||n>=perCompany)return false;
    selected.push(r);counts.set(company,n+1);return true;};
  const close=candidates.filter(r=>r[9]>=(candidates[0]?.[9]||0)-10);
  const slots=Math.round(Math.min(5,limit)*defenseTarget);
  for(const [sector,target] of [[true,slots],[false,Math.min(5,limit)-slots]]) {
    let n=0;for(const r of close)if(n<target&&defenseIds.has(String(r[15]))===sector&&add(r))n++;
  }
  candidates.forEach(add);return selected.sort((a,b)=>b[9]-a[9]);
}

function dailyModel(rows, previous={}, options={}) {
  const now=options.now||new Date();
  const day=options.day||localDay(now);
  const target=Math.min(5,options.target||3), perCompany=2;
  const applied=new Set(rows.filter(r=>r[0]!=='Not Applied').map(r=>String(r[15])));
  const allReady=rows.filter(r=>ready(r,now,applied));
  const byId=new Map(allReady.map(r=>[String(r[15]),r]));
  const selected=[], counts=new Map();
  function add(r){if(!r||selected.length>=target||(counts.get(r[4])||0)>=perCompany||selected.includes(r))return;
    selected.push(r);counts.set(r[4],(counts.get(r[4])||0)+1);}
  if(previous.day===day)(previous.ids||[]).forEach(id=>add(byId.get(id)));
  // Preserve valid assignments, then refill from the qualified portion of the queue.
  shortlist(rows,5,2,options.defenseIds||new Set(),options.defenseTarget||.725,now).forEach(add);
  allReady.sort((a,b)=>b[9]-a[9]).forEach(add);
  const queue=[...selected], seen=new Set(selected.map(r=>String(r[15])));
  for(const r of queueCandidates(rows,now)){
    if(queue.length>=Math.min(25,options.queueLimit||24))break;
    if(seen.has(String(r[15]))||(counts.get(r[4])||0)>=perCompany)continue;
    seen.add(String(r[15]));queue.push(r);counts.set(r[4],(counts.get(r[4])||0)+1);
  }
  const fallback=selected.length?[]:queue.filter(r=>['Hold','Stretch'].includes(r[23])).slice(0,3);
  const cause=queue.filter(r=>r[23]==='Hold'&&r[26]!=='Verified active').length ? 'Application-enabled verification is the main remaining blocker; automatic rechecks are prioritized.' : queue.some(r=>r[23]==='Stretch') ? 'Remaining roles have meaningful qualification gaps; no weak roles added to meet a quota.' : 'No suitable unapplied roles currently meet the evidence checks.';
  return {day,ids:selected.map(r=>String(r[15])),daily:selected,queue,fallback,reason:selected.length<3?cause:''};
}

function todayFormula(){return '='+['Applied','Interviewing','Offer','Rejected','Withdrawn'].map(s=>'COUNTIFS(Jobs!B2:B,">="&TODAY(),Jobs!B2:B,"<"&TODAY()+1,Jobs!A2:A,"'+s+'")').join('+');}
function totalApplicationsFormula(){return '='+['Applied','Interviewing','Offer','Rejected','Withdrawn'].map(s=>statusFormula(s).slice(1)).join('+');}
function followupsFormula(){return '='+['Applied','Interviewing','Offer'].map(s=>'COUNTIFS(Jobs!C2:C,">0",Jobs!C2:C,"<="&TODAY(),Jobs!A2:A,"'+s+'")').join('+');}

function statusFormula(status) {
  if (!STATUSES.includes(status)) throw new Error('Unknown application status: ' + status);
  return '=COUNTIF(Jobs!A2:A,"' + status + '")';
}

function ensureView(ss, name, oldName) {
  let sh=ss.getSheetByName(name)||ss.getSheetByName(oldName);
  if(sh && sh.getName && sh.getName()!==name)sh.setName(name);
  return sh||ss.insertSheet(name);
}

function refreshDashboard(ss, rows=[], model={daily:[],reason:''}) {
  const sh=ensureView(ss,'Daily Dashboard','Dashboard');
  const generatedLayout=sh.getRange(1,1,60,12);
  if(generatedLayout.breakApart)generatedLayout.breakApart();
  sh.getRange(1,1,60,12).clearContent();
  sh.getRange(1,1).setValue('Daily Dashboard');
  sh.getRange(2,1).setValue('=IF(NOW()-Settings!B3>1.5,"STALE FEED — recommendations paused","Feed current")&" | Collected "&TEXT(Settings!B3,"mmm d hh:mm")&" | Synced "&TEXT(Settings!B4,"mmm d hh:mm")');
  sh.getRange(3,1).setValue('Open posting → check qualifications → choose resume → apply → record in Jobs A:D. Job search menu → Refresh dashboard / refill. Optional defer: Jobs AI.');
  sh.getRange(4,1,1,9).setValues([['Today completed',todayFormula(),'Total applications',totalApplicationsFormula(),'Interviewing',statusFormula('Interviewing'),'Offer',statusFormula('Offer'),'Dates shown in America/Indianapolis']]);
  sh.getRange(5,1,1,9).setValues([['Rejected',statusFormula('Rejected'),'Applied',statusFormula('Applied'),'Follow-ups due',followupsFormula(),'Not Applied',statusFormula('Not Applied'),'Edit Jobs A:D to record an application']]);
  sh.getRange(6,1).setValue('=IF(COUNTIF(Sources!B2:B1000,"failed")+COUNTIF(Sources!B2:B1000,"partial")>0,"Source warning: "&TEXTJOIN(", ",TRUE,FILTER(Sources!A2:A1000,Sources!B2:B1000<>"ok",Sources!A2:A1000<>"")),"All employer sources collected successfully")');
  sh.getRange(7,1).setValue(model.daily.length ? 'Applications for Today — '+model.daily.length+' Recommended. Default target: three; Job search menu offers up to five. '+(model.reason||'Timing caveats are informational; decide whether the work interests you.') : 'No verified recommendations. '+(model.reason||'Automatic checks pending.')+' Showing up to three candidates only, with explicit blockers.');
  sh.getRange(8,1,1,9).setValues([['Company','Job / employer link','Location','Priority / fit','Employer posted','Resume','Recommendation / uncertainty','Why this role','Record']]);
  const jobs=ss.getSheetByName('Jobs'), index=indexRows(rows);
  const track=r=>'=HYPERLINK("'+ss.getUrl()+'#gid='+jobs.getSheetId()+'&range=A'+index.get(String(r[15]))+'","Record / defer")';
  const link=r=>'=HYPERLINK("'+String(r[14]).replace(/"/g,'""')+'","'+String(r[5]).replace(/"/g,'""')+'")';
  const displayed=model.daily.length?model.daily:(model.fallback||[]);
  if(displayed.length)sh.getRange(9,1,displayed.length,9).setValues(displayed.map(r=>[
    textCell(r[4]),link(r),textCell(String(r[6]).length>100?'Multiple locations; see posting':r[6]),r[9]+' / '+r[7],r[20]||'Unknown',textCell(r[31]),(model.daily.length?'Recommended — ':'Candidate only / '+r[23]+' — ')+textCell(r[24]),textCell(model.daily.length?r[25]:(r[28]||r[25])),track(r)]));
  sh.getRange(9,5,5,1).setNumberFormat('mmm d, yyyy');
  sh.getRange(15,1).setValue('Follow-ups due / overdue — records and dates preserved');
  sh.getRange(16,1,1,9).setValues([['Company','Role','Employer posted','Status','Follow-up due','Notes / action','','','Record']]);
  const today=localDay();
  const due=rows.filter(r=>['Applied','Interviewing','Offer'].includes(r[0])&&calendarDate(r[2])&&calendarDate(r[2])<=today).sort((a,b)=>calendarDate(a[2]).localeCompare(calendarDate(b[2])));
  model.followupCount=Math.min(8,due.length);
  if(due.length)sh.getRange(17,1,Math.min(8,due.length),9).setValues(due.slice(0,8).map(r=>[textCell(r[4]),textCell(r[5]),r[20]||'Unknown',r[0],r[2],textCell(r[0]==='Offer'&&r[4]==='RTX'?'Confirm written offer and decision deadline. '+r[3]:r[3]||'Review application / recruiter next step'),'','',track(r)]));
  else sh.getRange(17,1).setValue('No recorded follow-ups due.');
  sh.getRange(17,3,8,1).setNumberFormat('mmm d, yyyy');
  sh.getRange(17,4,8,1).setNumberFormat('@');
  sh.getRange(17,5,8,1).setNumberFormat('mmm d, yyyy');
  sh.getRange(26,1,1,4).setValues([['Verified active','=COUNTIF(Jobs!AA2:AA,"Verified active")','Unverified','=COUNTIF(Jobs!AA2:AA,"Unverified")']]);
  sh.getRange(27,1,1,4).setValues([['Stale checks','=COUNTIF(Jobs!AA2:AA,"Stale")','Confirmed closed','=COUNTIF(Jobs!AA2:AA,"Confirmed closed")']]);
  sh.getRange(28,1,1,8).setValues([['Recommended','=COUNTIF(Jobs!X2:X,"Recommended")','Stretch','=COUNTIF(Jobs!X2:X,"Stretch")','Hold','=COUNTIF(Jobs!X2:X,"Hold")','Duplicate','=COUNTIF(Jobs!X2:X,"Duplicate")']]);
  sh.getRange(31,1,1,4).setValues([['Not Interested',statusFormula('Not Interested'),'Withdrawn',statusFormula('Withdrawn')]]);
  sh.getRange(29,1).setValue('Resume categories are suggestions; no tailored resume is generated automatically. Open listings do not establish interview activity.');
  if(sh.setFrozenRows)sh.setFrozenRows(8);
}

function refreshViews(options={}) {
  const ss=SpreadsheetApp.getActiveSpreadsheet(),jobs=ss.getSheetByName('Jobs');
  const rows=jobs.getLastRow()>1?jobs.getRange(2,1,jobs.getLastRow()-1,HEADERS.length).getValues():[];
  const props=PropertiesService.getDocumentProperties();
  const previous=JSON.parse(props.getProperty('dailySelection')||'{}');
  if(!options.skipVerification)verifyUnapplied(ss,rows,loadChunks(props,'verificationHints'),8);
  const stamp=ss.getSheetByName('Settings').getRange('B3').getValue();
  const feedFresh=ageHours(stamp)<=36;
  const day=localDay();
  const model=dailyModel(rows,previous,{day,target:props.getProperty('capacityDay')===day?5:Number(props.getProperty('dailyTarget'))||3,queueLimit:Number(props.getProperty('priorityQueueLimit'))||24,defenseIds:new Set(loadChunks(props,'defenseIds'))});
  if(!feedFresh){model.daily=[];model.ids=[];model.fallback=model.queue.slice(0,3);model.reason='Feed is over 36 hours old or missing; wait for successful collection / sync.';}
  props.setProperty('dailySelection',JSON.stringify({day:model.day,ids:model.ids}));
  const view=ensureView(ss,'Priority Queue','Apply Next');
  view.getRange(1,1,60,12).clearContent();
  view.getRange(1,1).setValue('Priority Queue');
  view.getRange(2,1).setValue(model.queue.length+' opportunities. Today rows are assigned to Daily Dashboard; Backlog is remaining work. Stretch and Hold are not verified recommendations.');
  view.getRange(3,1,1,QUEUE_HEADERS.length).setValues([QUEUE_HEADERS]);
  const index=indexRows(rows),assigned=new Set(model.ids);
  const values=model.queue.map(r=>[assigned.has(String(r[15]))?'Today':'Backlog',feedFresh&&ready(r)?'Recommended':r[23]==='Stretch'?'Stretch':'Hold',textCell(r[4]),
    '=HYPERLINK("'+String(r[14]).replace(/"/g,'""')+'","'+String(r[5]).replace(/"/g,'""')+'")',textCell(String(r[6]).length>100?'Multiple US locations; see posting':r[6]),r[9],r[20]||'Unknown',textCell(r[10]+' | '+r[24]),
    textCell((ageHours(r[27])>72&&r[26]==='Verified active'?'Stale':r[26]||'Unverified')+' | '+(r[30]||'')+' | '+(r[32] instanceof Date?r[32].toISOString():'Check pending')),textCell(r[31]),textCell(r[25]+' | '+(r[23]==='Recommended'?'Confirm personal qualifications / authorization':r[24])),
    '=HYPERLINK("'+ss.getUrl()+'#gid='+jobs.getSheetId()+'&range=A'+index.get(String(r[15]))+'","Record / defer")']);
  if(values.length){view.getRange(4,1,values.length,12).setValues(values);view.getRange(4,7,values.length,1).setNumberFormat('mmm d, yyyy');}
  refreshDashboard(ss,rows,model);
  if(ss.setActiveSheet){const dashboard=ss.getSheetByName('Daily Dashboard');ss.setActiveSheet(dashboard);ss.moveActiveSheet(1);}
  formatViews(ss,model);
}

function formatViews(ss,model={daily:[]}) {
  for(const [name,widths] of [['Daily Dashboard',[105,225,110,75,95,110,190,185,100]],['Priority Queue',[85,115,125,280,145,75,110,270,255,130,260,115]]]){
    const sh=ss.getSheetByName(name);if(!sh||!sh.setColumnWidth)continue;
    widths.forEach((w,i)=>sh.setColumnWidth(i+1,w));
    sh.getRange(1,1,35,widths.length).setWrap(true).setVerticalAlignment('middle');
    sh.getRange(name==='Daily Dashboard'?8:3,1,1,widths.length).setFontWeight('bold').setBackground('#e8eaed');
    if(name==='Daily Dashboard'){
      sh.setRowHeights(1,35,26);sh.setRowHeight(4,44);sh.setRowHeight(5,36);
      sh.getRange(1,1).setFontSize(14).setFontWeight('bold');
      sh.getRange(16,1,1,9).setFontWeight('bold').setBackground('#e8eaed');
      for(const r of [1,2,3,6,7,15,29])sh.getRange(r,1,1,9).mergeAcross();
      for(let r=16;r<=24;r++)sh.getRange(r,6,1,3).mergeAcross();
      sh.setRowHeight(2,36);sh.setRowHeight(3,42);sh.setRowHeight(6,36);sh.setRowHeight(7,64);sh.setRowHeight(29,40);
      const n=model.daily.length||(model.fallback||[]).length;if(n)sh.setRowHeights(9,n,120);
      if(model.followupCount)sh.setRowHeights(17,model.followupCount,95);
    }else {sh.getRange(1,1,1,12).mergeAcross();sh.getRange(2,1,1,12).mergeAcross();sh.setRowHeight(2,42);sh.setRowHeights(4,25,96);}
    if(sh.setHiddenGridlines)sh.setHiddenGridlines(true);
  }
}

function showFiveRecommendations(){PropertiesService.getDocumentProperties().setProperty('capacityDay',localDay());refreshViews();}

function installDailyTrigger() {
  // Only replace this script's sync trigger; never touch unrelated automations.
  ScriptApp.getProjectTriggers().filter(t=>t.getHandlerFunction()==='syncJobs').forEach(t=>ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger('syncJobs').timeBased().everyDays(1).atHour(15).inTimezone('Etc/UTC').create();
}

if (typeof module !== 'undefined') module.exports = {autoFields,validateFeed,indexRows,shortlist,textCell,statusFormula,HEADERS,STATUSES,QUEUE_HEADERS,ready,dailyModel,queueCandidates,ageHours,localDay,calendarDate,submittedToday,saveChunks,loadChunks,verifyHint,verifyUnapplied,DECISIONS,todayFormula,totalApplicationsFormula};
