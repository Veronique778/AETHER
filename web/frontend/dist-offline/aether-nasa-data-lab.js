/* AETHER NASA Data Lab 1.4 — public research context only, no astronaut vitals.
 * CANONICAL SOURCE: web/frontend/public/aether-nasa-data-lab.js. dist-offline/ is build output
 * (scripts/build-offline.mjs copies this file and verifies feature markers; see feature-manifest.json). */
(() => {
  'use strict';
  if (document.getElementById('aether-nasa-launch')) return;
  const css = `
#aether-nasa-launch{position:fixed;bottom:20px;right:20px;z-index:9999;border:1px solid #23c9b3;background:#062735;color:#eafffb;padding:12px 17px;border-radius:999px;box-shadow:0 8px 35px #0009;font:700 13px system-ui;cursor:pointer;letter-spacing:.04em}
#aether-nasa-overlay{position:fixed;inset:0;z-index:10000;background:#010816da;display:none;align-items:center;justify-content:center;padding:20px;font:14px system-ui;color:#e6f5fa}
#aether-nasa-overlay.open{display:flex}
#aether-nasa-modal{position:relative;width:min(1040px,96vw);max-height:93vh;overflow:auto;border:1px solid #28677b;border-radius:20px;background:linear-gradient(145deg,#061723,#091f2e);box-shadow:0 28px 110px #000c;padding:24px}
#aether-nasa-modal h2{font-size:24px;font-weight:750;letter-spacing:.03em;margin:0 36px 4px 0}
#aether-nasa-modal h3{font-size:17px;font-weight:700;margin:0 0 9px}
#aether-nasa-modal p{margin:6px 0 12px;line-height:1.55}
#aether-nasa-modal a{color:#8fefd9;text-decoration:underline}
#aether-nasa-modal button{border:1px solid #377b8e;border-radius:10px;background:#123b4d;color:#edfffa;padding:9px 12px;cursor:pointer;font-weight:650}
#aether-nasa-modal button:disabled{opacity:.55;cursor:wait}
#aether-nasa-modal input,#aether-nasa-modal select{border:1px solid #48677c;border-radius:9px;background:#081e2b;color:#fff;padding:9px;min-width:0}
#aether-nasa-modal input[type=file]{max-width:100%}
.aether-nasa-muted{color:#a6bcc9;font-size:12px}.aether-nasa-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}
.aether-nasa-card{background:#102837;border:1px solid #285064;border-radius:13px;padding:15px;margin-top:13px;overflow-wrap:anywhere}
.aether-nasa-control{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.aether-nasa-input{flex:1;min-width:180px}
.aether-nasa-result{padding:10px 0;border-bottom:1px solid #294450}.aether-nasa-result:last-child{border-bottom:0}
.aether-nasa-status{padding:12px;border-radius:9px;border:1px solid #405867;background:#112a39;margin:10px 0;min-height:20px}
.aether-nasa-pill{border:1px solid #478982;border-radius:20px;padding:3px 8px;font-size:11px;color:#9decde;display:inline-block;margin-right:5px}
.aether-nasa-table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums;margin-top:10px}.aether-nasa-table td,.aether-nasa-table th{border-bottom:1px solid #375163;padding:8px;text-align:left}
#aether-nasa-close{position:absolute;top:15px;right:18px;font-size:25px;line-height:1;padding:5px 11px}
@media(max-width:740px){.aether-nasa-grid{grid-template-columns:1fr}#aether-nasa-modal{padding:17px}#aether-nasa-launch{bottom:9px;right:9px}}
`;
  const style = document.createElement('style'); style.textContent = css; document.head.appendChild(style);
  const launcher = document.createElement('button'); launcher.id='aether-nasa-launch'; launcher.type='button'; launcher.textContent='NASA DATA LAB'; launcher.setAttribute('aria-label','Open NASA Open Data Research Lab'); document.body.appendChild(launcher);
  const overlay = document.createElement('div'); overlay.id='aether-nasa-overlay'; overlay.setAttribute('role','dialog');overlay.setAttribute('aria-modal','true');overlay.setAttribute('aria-label','NASA Data Lab');
  overlay.innerHTML=`<div id="aether-nasa-modal">
    <button type="button" id="aether-nasa-close" aria-label="Close NASA Data Lab">×</button>
    <h2>NASA DATA LAB <span class="aether-nasa-pill">OSDR / NASA-STD-3001</span></h2>
    <p class="aether-nasa-muted">Evidence-backed research mode · NASA studies and ISS environmental data are NOT live astronaut measurements.</p>
    <div class="aether-nasa-grid">
      <section class="aether-nasa-card"><h3>01 · NASA evidence & hazards</h3>
        <p>NASA-STD-3001 Volume 1 guides crew-health requirements; Volume 2 addresses habitability, environment and performance. These standards are scientific context, <strong>not certification</strong> of AETHER.</p>
        <p><a href="https://www.nasa.gov/reference/nasa-std-3001v1/" target="_blank" rel="noopener noreferrer">NASA Standard Vol. 1 ↗</a> · <a href="https://www.nasa.gov/reference/nasa-std-3001v2/" target="_blank" rel="noopener noreferrer">Vol. 2 ↗</a></p>
        <p>NASA OSDR EDA offers actual ISS cabin/hardware environmental and radiation telemetry from <strong>Rodent Research missions</strong>; this is not automatically equivalent to crew exposure.</p>
        <p><a href="https://visualization.osdr.nasa.gov/eda/" target="_blank" rel="noopener noreferrer">Explore NASA ISS Environmental Data ↗</a></p>
        <div class="aether-nasa-muted">Use EDA → Data Tables → download CSV → analyze below. Never merge these records with live wearable measurements without explicit study design.</div>
      </section>
      <section class="aether-nasa-card"><h3>02 · Live NASA OSDR studies</h3>
        <div class="aether-nasa-control"><input id="aether-nasa-term" class="aether-nasa-input" maxlength="90" placeholder="e.g. cardiovascular / radiation / sleep" value="cardiovascular" />
          <button type="button" id="aether-nasa-search">Search NASA</button></div>
        <p class="aether-nasa-muted">Study titles and accession IDs come from NASA OSDR public API, not generated scenarios. Network required; cache may be used.</p>
        <div id="aether-nasa-search-status" class="aether-nasa-status" role="status">Search NASA to load real study metadata.</div>
        <div id="aether-nasa-studies"></div>
      </section>
      <section class="aether-nasa-card"><h3>03 · Explore NASA dataset files</h3>
        <p class="aether-nasa-muted">Enter an OSD study number from the results above. Files may include assays, metadata, or restricted downloads — not necessarily pulse/sleep data.</p>
        <div class="aether-nasa-control"><input id="aether-nasa-study-id" inputmode="numeric" pattern="[0-9]+" placeholder="OSD study ID" aria-label="OSD study number" />
          <button type="button" id="aether-nasa-files-btn">List public files</button></div>
        <div id="aether-nasa-files-status" class="aether-nasa-status" role="status">Choose a study to inspect its source files.</div>
        <div id="aether-nasa-files"></div>
        <button id="aether-nasa-history" type="button" style="margin-top:10px">Saved NASA research imports (offline)</button>
        <div id="aether-nasa-history-list"></div>
        <div id="aether-nasa-verified" class="aether-nasa-card" style="display:none; margin-top:10px">
          <strong>Import an OSDR-listed CSV/TSV</strong>
          <p class="aether-nasa-muted">Downloaded by AETHER directly from the file URL in the official OSDR catalog (HTTPS, no redirects, max 3 MB). Source, SHA-256, organism and preprocessing are recorded. Units are read from the column header only — never inferred.</p>
          <div id="aether-nasa-verified-label"></div>
          <div class="aether-nasa-control" style="margin-top:8px"><select id="aether-nasa-verified-column" aria-label="NASA verified CSV column"></select><select id="aether-nasa-verified-label-column" aria-label="Sample label column (timepoints)"><option value="">No timepoint labels</option></select><button type="button" id="aether-nasa-verified-run">Analyze verified NASA file</button></div>
          <div class="aether-nasa-status" id="aether-nasa-verified-status" role="status">Choose a column.</div>
          <div id="aether-nasa-verified-results"></div>
        </div>
      </section>
      <section class="aether-nasa-card"><h3>04 · Analyze research CSV</h3>
        <p>Select a <strong>downloaded CSV</strong> (for example from NASA EDA). AETHER performs numeric descriptive analysis in the local backend; it does not make health diagnoses.</p>
        <label class="aether-nasa-muted" for="aether-nasa-local-study">OSD study number of this file (optional — saves to history as <strong>unverified</strong>)</label>
        <input id="aether-nasa-local-study" inputmode="numeric" pattern="[0-9]+" placeholder="e.g. 575" aria-label="OSD study number for local file" />
        <label class="aether-nasa-muted" for="aether-nasa-csv">Source file (max 3 MB)</label>
        <input type="file" id="aether-nasa-csv" accept=".csv,.tsv,text/csv,text/tab-separated-values" />
        <div class="aether-nasa-control" style="margin-top:8px"><select id="aether-nasa-column" aria-label="CSV numeric column"><option value="">Select file first</option></select>
          <button type="button" id="aether-nasa-analyze">Compute summary</button></div>
        <div id="aether-nasa-csv-status" class="aether-nasa-status" role="status">No file loaded.</div>
        <div id="aether-nasa-stats"></div>
        <p class="aether-nasa-muted">Provenance: uploaded local file, <strong>NASA origin NOT independently verified</strong>. Do not mix with PHANTOM astronaut telemetry. Cite dataset ID, file and original units.</p>
      </section>
      <section class="aether-nasa-card"><h3>05 · Live Watch / BLE heart rate</h3>
        <p>Compatible Bluetooth <strong>Heart Rate Service (0x180D)</strong> monitors only. Most watches need HR broadcast mode. The scan does not prove compatibility. No automatic access to Apple Health, Samsung Health, SpO₂ or sleep.</p>
        <div class="aether-nasa-control">
          <button id="aether-ble-scan" type="button">Scan HRS devices</button>
          <button id="aether-ble-scan-all" type="button" disabled>Scan all named devices (verify profile)</button>
          <button id="aether-ble-disconnect" type="button">Save & disconnect</button>
        </div>
        <div id="aether-ble-status" class="aether-nasa-status" role="status">Sensor status will appear here.</div>
        <div id="aether-ble-devices"></div>
        <p class="aether-nasa-muted">Human Earth readings are saved in BIOSIGNALS. No physiological reading appears unless a real device sends a valid notification; sensor hardware has not been verified for this release.</p>
      </section>
    </div>
    <p class="aether-nasa-muted" style="margin-top:13px" data-aether-provenance-legend="1">Provenance classes: <span class="aether-nasa-pill">NASA research data</span><span class="aether-nasa-pill">real terrestrial wearable</span><span class="aether-nasa-pill">synthetic mission simulation</span><span class="aether-nasa-pill">model-derived estimate</span>. Only human in vivo clinical data from a verified NASA download is shown to PHANTOM, as read-only context. AETHER sources: NASA OSDR studies / NASA ISS environmental telemetry / MMASH Earth biosignals / BLE Earth sensor / synthetic mission. Each source has different validity and must stay labelled separately.</p>
  </div>`;
  document.body.appendChild(overlay);
  const by = id => overlay.querySelector('#'+id);
  const mk = (tag, text, className) => { const el = document.createElement(tag); el.textContent=String(text??'');if(className)el.className=className;return el; };
  const show = () => { overlay.classList.add('open');by('aether-nasa-close').focus(); }; const hide=()=>{overlay.classList.remove('open');launcher.focus();};
  launcher.addEventListener('click',show); by('aether-nasa-close').addEventListener('click',hide);
  overlay.addEventListener('click',ev=>{if(ev.target===overlay)hide();});document.addEventListener('keydown',ev=>{if(ev.key==='Escape'&&overlay.classList.contains('open'))hide();});
  const sessionToken = () => document.querySelector('meta[name="aether-session-token"]')?.getAttribute('content') || window.__AETHER_TOKEN__ || '';
  const req = async(url, opts={}) => {const headers={...(opts.headers||{})};const t=sessionToken();if(t&&!window.__aetherFetch)headers['X-AETHER-Token']=t;const res=await fetch(url, {...opts,headers});let data;try{data=await res.json()}catch{throw Error('NASA endpoint did not return JSON');}if(!res.ok)throw Error(String(data.detail||data.error||`HTTP ${res.status}`));return data;};
  by('aether-nasa-search').addEventListener('click',async()=>{
    const button=by('aether-nasa-search');button.disabled=true;const status=by('aether-nasa-search-status'),list=by('aether-nasa-studies');list.replaceChildren();status.textContent='Requesting NASA OSDR metadata…';
    try {const term=by('aether-nasa-term').value.trim().slice(0,90)||'human physiology';const data=await req('/api/nasa/catalog?term='+encodeURIComponent(term)+'&refresh=true');
      status.textContent=(data.warning||`${(data.studies||[]).length} study results`) + (data.available===false?' · offline — nothing shown':data.cached?' · cached metadata':' · '+(data.source_label||'NASA OSDR API'));
      for(const study of (data.studies||[])) {const div=mk('div','', 'aether-nasa-result');const title=mk('div',(study.accession||'Unknown ID')+' — '+(study.title||'Untitled study'));div.appendChild(title);
        if(study.evidence_class){const meta=mk('div','', 'aether-nasa-muted');meta.setAttribute('data-evidence-class',study.evidence_class);meta.appendChild(mk('span',study.evidence_class.replace(/_/g,' '),'aether-nasa-pill'));meta.appendChild(mk('span',study.data_layer.replace(/_/g,' '),'aether-nasa-pill'));meta.appendChild(mk('span',`Organism: ${study.organism}${study.mission?' · '+study.mission:''} · ${study.evidence_label}`));div.appendChild(meta);}
        if(study.official_url){const a=mk('a','Official OSDR study page ↗');a.href=study.official_url;a.target='_blank';a.rel='noopener noreferrer';a.style.marginRight='8px';div.appendChild(a);}const match=String(study.accession||'').match(/OSD-(\d+)/i);if(match){const btn=mk('button','Inspect files');btn.style.marginTop='6px';btn.addEventListener('click',()=>{by('aether-nasa-study-id').value=match[1];by('aether-nasa-files-btn').click();});div.appendChild(btn);}list.appendChild(div);}
      if(!(data.studies||[]).length)list.textContent='No studies were returned for this query. Try a different keyword.';
    }catch(err){status.textContent='NASA catalog unavailable: '+err.message;}finally{button.disabled=false;}
  });
  by('aether-nasa-files-btn').addEventListener('click',async()=>{
    const id=by('aether-nasa-study-id').value.trim(),button=by('aether-nasa-files-btn'),list=by('aether-nasa-files'),status=by('aether-nasa-files-status');list.replaceChildren();
    if(!/^\d{1,6}$/.test(id)){status.textContent='Enter a numeric study ID.';return;}button.disabled=true;status.textContent='Checking NASA OSDR file catalogue…';
    try {const data=await req(`/api/nasa/studies/${id}/files`);const files=Array.isArray(data.files)?data.files:[];status.textContent=`OSD-${id}: ${files.length} file entries. Some files may be restricted.`;
      for(const file of files.slice(0,80)){const div=mk('div','', 'aether-nasa-result');div.appendChild(mk('span',(file.name||'Unnamed file')+(file.category?' · '+file.category:'')+(file.size_bytes?' · '+Number(file.size_bytes).toLocaleString()+' B':'')+(file.restricted?' · restricted':'')));
        div.appendChild(mk('div',(file.supported?'Importable · ':'Not imported · ')+(file.format||'?')+' · '+(file.parser||''),'aether-nasa-muted'));
        if(file.download_url&&!file.restricted){try{const u=new URL(file.download_url);const official=u.protocol==='https:'&&u.hostname==='osdr.nasa.gov';if(official||u.hostname==='127.0.0.1'){const a=mk('a',official?' · download at NASA':' · download from TEST MIRROR (not NASA)');a.href=u.href;a.target='_blank';a.rel='noopener noreferrer';div.appendChild(a);}}catch{}}
        if(file.name && file.supported && file.download_url && !file.restricted){
          const verify=mk('button','Inspect & import from NASA');verify.style.marginLeft='7px';
          verify.addEventListener('click',()=>void inspectVerifiedNASA(Number(id),file.name));div.appendChild(verify);
        }
        list.appendChild(div);}
      if(!files.length)list.textContent='This study returned no public files (or API schema differs). Check the NASA source website.';
    }catch(err){status.textContent='Could not list NASA study files: '+err.message;}finally{button.disabled=false;}
  });
  by('aether-nasa-history').addEventListener('click',async()=>{
    const out=by('aether-nasa-history-list');out.replaceChildren();
    try {const d=await req('/api/nasa/imports');const entries=d.imports||[];
      if(!entries.length){out.textContent='No NASA research imports yet. Search a study, choose a public CSV, and analyze it.';return;}
      for(const entry of entries.slice().reverse()){
        const item=mk('div','', 'aether-nasa-result');
        item.setAttribute('data-import-id',entry.import_id||'');
        item.appendChild(mk('div',`${entry.study} · ${entry.filename} · ${entry.column} · n=${entry.summary?.count??'—'} · mean=${entry.summary?.mean??'—'} ${entry.unit&&!/^not stated/.test(entry.unit)?entry.unit:'(unit not stated)'}`));
        item.appendChild(mk('div',`${entry.source_label||entry.source_type} · organism: ${entry.organism||'not recorded'} · ${String(entry.evidence_class||'unclassified').replace(/_/g,' ')} · ${String(entry.data_layer||'unclassified').replace(/_/g,' ')}`,'aether-nasa-muted'));
        item.appendChild(mk('div',`PHANTOM: ${entry.phantom_reference?.eligible?'eligible as read-only reference context':'not used'} — ${(entry.phantom_reference?.reasons||[]).join('; ')}`,'aether-nasa-muted'));
        item.appendChild(mk('small',`SHA-256 ${entry.sha256} · ${entry.retrieved_at_utc}`));
        const href=entry.official_url||entry.download_url;if(href){const link=mk('a',' · Official source');link.href=href;link.target='_blank';link.rel='noopener noreferrer';item.appendChild(link);}out.appendChild(item);
      }
    }catch(err){out.textContent='Verified import history unavailable: '+err.message;}
  });
  let verifiedFile = null;
  const verifiedRequest=async(body)=>req('/api/nasa/verified-csv',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const inspectVerifiedNASA=async(studyId,filename)=>{
    const box=by('aether-nasa-verified'),status=by('aether-nasa-verified-status'),cols=by('aether-nasa-verified-column');
    box.style.display='block';cols.replaceChildren();by('aether-nasa-verified-results').replaceChildren();
    by('aether-nasa-verified-label').textContent=`OSD-${studyId} · ${filename}`;
    status.textContent='Fetching CSV from official NASA OSDR source (max 3 MB)...';
    verifiedFile=null;by('aether-nasa-verified-run').disabled=true;
    try{
      const result=await verifiedRequest({study_id:studyId,filename});
      verifiedFile={study_id:studyId,filename};
      const numeric=result.numeric_columns&&result.numeric_columns.length?result.numeric_columns:(result.columns||[]);
      for(const col of numeric){const opt=document.createElement('option');opt.value=col;opt.textContent=col;cols.appendChild(opt);}
      const labels=by('aether-nasa-verified-label-column');labels.replaceChildren(mk('option','No timepoint labels'));labels.firstChild.value='';
      for(const col of result.columns||[]){if(numeric.includes(col))continue;const opt=document.createElement('option');opt.value=col;opt.textContent=col;labels.appendChild(opt);}
      const p=result.provenance;
      status.textContent=`${p.source_label} · SHA-256: ${p.sha256} · ${p.file_size_bytes} bytes${p.size_matches_catalog===false?' · SIZE DIFFERS FROM CATALOG':''} · organism: ${p.organism} (${p.evidence_label}). Choose a numeric column.`;
      by('aether-nasa-verified-run').disabled=!numeric.length;
    }catch(error){status.textContent='Could not verify NASA file: '+error.message;}
  };
  by('aether-nasa-verified-run').addEventListener('click',async()=>{
    const button=by('aether-nasa-verified-run'),status=by('aether-nasa-verified-status'),out=by('aether-nasa-verified-results');
    if(!verifiedFile)return;button.disabled=true;out.replaceChildren();status.textContent='Downloading original NASA file and verifying its SHA-256...';
    try{
      const result=await verifiedRequest({...verifiedFile,column:by('aether-nasa-verified-column').value,label_column:by('aether-nasa-verified-label-column').value});
      const rows=[['Study',result.provenance.study],['CSV file',result.provenance.filename],['Numeric column',result.summary.column],
        ['Valid measurements',result.summary.count],['Mean',result.summary.mean],['Median',result.summary.median],
        ['Minimum',result.summary.minimum],['Maximum',result.summary.maximum],['Sample SD',result.summary.std_dev??'—'],
        ['Unit (from header only)',result.summary.unit],
        ['Excluded: missing / non-numeric or censored',`${result.summary.missing_values.missing_tokens} / ${result.summary.missing_values.non_numeric_or_censored}${result.summary.missing_values.non_numeric_examples.length?' (e.g. '+result.summary.missing_values.non_numeric_examples.join(', ')+')':''}`],
        ['Organism / evidence class',`${result.provenance.organism} · ${result.provenance.evidence_label}`],['Data layer',result.provenance.data_layer],
        ['Source',result.provenance.source_label],['Source SHA-256',result.provenance.sha256],['Retrieved UTC',result.provenance.retrieved_at_utc],
        ['PHANTOM use',(result.phantom_reference?.eligible?'Read-only reference context':'Not used')+' — '+(result.phantom_reference?.reasons||[]).join('; ')]];
      const table=mk('table','','aether-nasa-table');table.setAttribute('aria-label','Verified NASA import summary');
      for(const [k,v] of rows){const tr=document.createElement('tr');tr.appendChild(mk('th',k));tr.appendChild(mk('td',v));table.appendChild(tr);}
      out.appendChild(table);
      if(result.summary.timepoints){const tp=mk('table','','aether-nasa-table');tp.setAttribute('aria-label','Timepoint summary');const head=document.createElement('tr');for(const h of ['Timepoint','Phase','n','Mean','Median'])head.appendChild(mk('th',h));tp.appendChild(head);
        for(const g of result.summary.timepoints.groups){const tr=document.createElement('tr');for(const v of [g.token,g.phase,g.count,g.mean,g.median])tr.appendChild(mk('td',v));tp.appendChild(tr);}out.appendChild(tp);
        out.appendChild(mk('p',`${result.summary.timepoints.note} Subjects detected: ${result.summary.timepoints.subjects_detected.join(', ')||'none'}.`,'aether-nasa-muted'));}
      const steps=mk('details','');steps.appendChild(mk('summary','Preprocessing history'));const ol=document.createElement('ol');for(const s of result.preprocessing||[])ol.appendChild(mk('li',s));steps.appendChild(ol);out.appendChild(steps);
      const a=mk('a','Official NASA CSV source');a.href=result.provenance.download_url;a.target='_blank';a.rel='noopener noreferrer';out.appendChild(a);
      status.textContent='Verified public OSDR file, statistics saved locally for offline presentation. Not astronaut telemetry or a clinical inference.';
    }catch(error){status.textContent='Verified analysis unavailable: '+error.message;}
    finally{button.disabled=false;}
  });
  let currentCsv='';let currentFile='';
  by('aether-nasa-csv').addEventListener('change',async()=>{
    const file=by('aether-nasa-csv').files?.[0],status=by('aether-nasa-csv-status'),selector=by('aether-nasa-column');currentCsv='';currentFile='';selector.replaceChildren();by('aether-nasa-stats').replaceChildren();if(!file)return;
    if(file.size>3_000_000){status.textContent='CSV exceeds 3 MB; use a smaller research extract.';return;}
    if(!/\.(csv|tsv)$/i.test(file.name)){status.textContent='Only .csv or .tsv files are supported.';return;}
    currentCsv=await file.text();currentFile=file.name;
    const header=(currentCsv.split(/\r?\n/,1)[0]||'').replace(/^\uFEFF/,'');const sep=header.includes('\t')?'\t':',';
    const columns=header.split(sep).slice(0,100).map(x=>x.replace(/^"|"$/g,'').trim()).filter(Boolean);
    for(const c of columns){const opt=document.createElement('option');opt.value=c;opt.textContent=c;selector.appendChild(opt);}
    status.textContent=`Loaded ${currentFile} (${file.size.toLocaleString()} bytes). Choose a numeric column and its original units from dataset documentation.`;
  });
  by('aether-nasa-analyze').addEventListener('click',async()=>{
    const status=by('aether-nasa-csv-status'),out=by('aether-nasa-stats'),button=by('aether-nasa-analyze');out.replaceChildren();if(!currentCsv){status.textContent='Choose a local CSV first.';return;}button.disabled=true;status.textContent='Computing descriptive statistics locally…';
    try{const sid=by('aether-nasa-local-study').value.trim();let d,saved='';
      if(/^\d{1,6}$/.test(sid)){const r=await req('/api/nasa/local-csv',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({study_id:Number(sid),filename:currentFile,content:currentCsv,column:by('aether-nasa-column').value})});d=r.summary;saved=` Saved to history as USER-SUPPLIED (unverified)${r.provenance.matches_previous_verified_download?'; SHA-256 matches an earlier verified NASA download':''}. SHA-256 ${r.provenance.sha256}.`;}
      else d=await req('/api/nasa/analyze-csv',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({csv:currentCsv,column:by('aether-nasa-column').value})});
      status.textContent=`Local CSV: ${currentFile}. NASA provenance unverified. No diagnostic or astronaut inference.`+saved;
      const table=mk('table','', 'aether-nasa-table');const values=[['Column',d.column],['Valid observations',d.count],['Mean',d.mean],['Median',d.median],['Minimum',d.minimum],['Maximum',d.maximum],['Sample SD',d.std_dev??'not available'],['Unit (from header only)',d.unit??'not stated'],['Excluded missing / non-numeric',d.missing_values?`${d.missing_values.missing_tokens} / ${d.missing_values.non_numeric_or_censored}`:'—']];
      for(const [k,v] of values){const row=document.createElement('tr');row.appendChild(mk('th',k));row.appendChild(mk('td',v));table.appendChild(row);}out.appendChild(table);
    }catch(err){status.textContent='Could not analyze CSV: '+err.message;}finally{button.disabled=false;}
  });
  const postBiosignal=async(path,data)=>req('/api/biosignals'+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  let bleBroad=false;
  const bleStatus=async()=>{
    try {const s=await req('/api/biosignals/sensor/status');
      by('aether-ble-status').textContent=(s.status||s.connection||'Unavailable')+' · pulse: '+(s.heart_rate??'—')+' bpm · quality: '+(s.quality||'unavailable')+' · samples: '+(s.received_samples??'not reported')+(s.error?' · '+s.error:'');
    } catch(err) {by('aether-ble-status').textContent='BLE backend unavailable: '+err.message;}
  };
  const initBle=async()=>{
    try{const d=await req('/api/biosignals/sensor/diagnostics');
      bleBroad=Array.isArray(d.modes)&&d.modes.includes('all_named_nearby_with_service_check');
      by('aether-ble-scan-all').disabled=!bleBroad;
    }catch{bleBroad=false;by('aether-ble-scan-all').disabled=true;}
    await bleStatus();
  };
  launcher.addEventListener('click',()=>{void initBle();});
  const bleScan=async(broad)=>{
    const status=by('aether-ble-status'),out=by('aether-ble-devices'),a=by('aether-ble-scan'),b=by('aether-ble-scan-all');
    if(broad&&!bleBroad){status.textContent='Broad search requires source build 1.2 and its BLE adapter; the existing frozen exe may only support advertised HRS.';return;}
    a.disabled=true;b.disabled=true;out.replaceChildren();status.textContent='Looking for BLE monitors. Enable Bluetooth and an HR broadcast mode…';
    try{const devices=await postBiosignal('/sensor/scan',{include_unadvertised:broad});
      status.textContent=`${devices.length} visible ${broad?'named device candidates':'HRS-advertising monitors'}. Actual compatibility is checked during GATT connection.`;
      for(const dev of devices){const div=mk('div','', 'aether-nasa-result');div.appendChild(mk('span',(dev.name||'Unnamed')+' · '+(dev.profile||'profile unverified')+' '));const connect=mk('button','Connect / verify');
        connect.addEventListener('click',async()=>{connect.disabled=true;status.textContent='Checking profile and connecting (no simulated fallback)…';
          try{const r=await postBiosignal('/sensor/connect',{device_id:dev.id});status.textContent=(r.status||r.connection||'')+(r.error?' · '+r.error:'');if(r.connection==='connected')await bleStatus();}
          catch(e){status.textContent='BLE connection failed: '+e.message;}finally{connect.disabled=false;}});div.appendChild(connect);out.appendChild(div);}
      if(!devices.length)out.textContent='No devices found. Check Windows Bluetooth permissions and enable Heart Rate broadcast on your monitor.';
    }catch(err){status.textContent='Could not scan BLE devices: '+err.message;}finally{a.disabled=false;b.disabled=!bleBroad;}
  };
  by('aether-ble-scan').addEventListener('click',()=>void bleScan(false));
  by('aether-ble-scan-all').addEventListener('click',()=>void bleScan(true));
  by('aether-ble-disconnect').addEventListener('click',async()=>{try{await postBiosignal('/sensor/disconnect',{});await bleStatus();}catch(e){by('aether-ble-status').textContent='Disconnect failed: '+e.message;}});
  setInterval(()=>{if(overlay.classList.contains('open'))void bleStatus();},3000);
})();
