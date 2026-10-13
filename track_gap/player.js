"use strict";
(() => {
  const raw = document.getElementById('timeline').textContent;
  const data = JSON.parse(raw);
  const $ = id => document.getElementById(id);
  const colors = ['#007c72','#b44f18','#604ab2','#136bab','#a62c60','#65751a','#874626','#345c68'];
  const selected = new Set(data.tracks.map(tr => tr.id));
  let current = data.start, playing = false, page = 1, visible = [], last = null, lastDraw = 0, animation = null;
  const all = data.tracks.flatMap(tr => tr.points.map(p => ({tr, p}))).sort((a,b) => a.p.t-b.p.t || a.tr.id-b.tr.id);
  const iso = t => new Date(t).toISOString();
  const esc = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&apos;'}[c]));
  const fmt = n => n === null ? '—' : n.toFixed(6);
  const number = n => Number(n.toFixed(6));
  const bounds = data.bounds;
  const midLat = (bounds.north+bounds.south)/2;
  const midLon = (bounds.east+bounds.west)/2;
  const cos = Math.cos(midLat*Math.PI/180);
  const width = Math.max((bounds.east-bounds.west)*cos, 0.0001);
  const height = Math.max(bounds.north-bounds.south, 0.0001);
  const scale = Math.min(760/width, 340/height);
  function xy(p) { return [450+(p.lon-midLon)*cos*scale, 250-(p.lat-midLat)*scale]; }
  function position(tr, t) {
    const ps = tr.points;
    let lo=0, hi=ps.length;
    while (lo<hi) { const m=(lo+hi)>>>1; if(ps[m].t<t) lo=m+1; else hi=m; }
    const b=ps[lo], a=ps[lo-1];
    if(b && b.t===t) return {status:'observed', lat:b.lat, lon:b.lon, reason:null};
    if(!a || !b) return {status:'unknown', lat:null, lon:null, reason:'outside-observations'};
    const reason = a.run!==b.run ? b.break_before : b.t-a.t>data.max_gap_ms ? 'max-gap' : null;
    if(reason) return {status:'unknown', lat:null, lon:null, reason};
    const f=(t-a.t)/(b.t-a.t);
    return {status:'interpolated',lat:a.lat+f*(b.lat-a.lat),lon:a.lon+f*(b.lon-a.lon),reason:null};
  }
  function snapshot() { return data.tracks.filter(tr=>selected.has(tr.id)).map(tr=>({id:tr.id,alias:tr.alias,...position(tr,current)})); }
  const canvas=$('plot'), ctx=canvas.getContext('2d');
  const backdrop=document.createElement('canvas'); backdrop.width=900; backdrop.height=500;
  const bg=backdrop.getContext('2d');
  function background() {
    bg.fillStyle='#f8fbfa'; bg.fillRect(0,0,900,500);
    bg.strokeStyle='#dce5e1'; bg.lineWidth=1; bg.setLineDash([]);
    for(let x=50;x<=850;x+=100){bg.beginPath();bg.moveTo(x,40);bg.lineTo(x,440);bg.stroke();}
    for(let y=50;y<=450;y+=100){bg.beginPath();bg.moveTo(40,y);bg.lineTo(860,y);bg.stroke();}
    bg.font='14px system-ui'; bg.fillStyle='#52636b';
    bg.fillText('N ↑ latitude',24,25); bg.fillText('longitude · E →',744,482);
    bg.fillText(`Center ${midLat.toFixed(5)}° N, ${midLon.toFixed(5)}° E`,24,482);
    for(const tr of data.tracks) {
      if(!selected.has(tr.id))continue;
      bg.strokeStyle=colors[tr.id%colors.length]; bg.fillStyle=bg.strokeStyle; bg.globalAlpha=.45;
      bg.lineWidth=1.5; bg.setLineDash([4,5]); bg.beginPath();
      for(let i=0;i<tr.points.length;i++) {
        const p=tr.points[i], a=tr.points[i-1], [x,y]=xy(p);
        if(a && p.run===a.run && p.t-a.t<=data.max_gap_ms) bg.lineTo(x,y); else bg.moveTo(x,y);
      }
      bg.stroke(); bg.setLineDash([]);
      for(const p of tr.points){ const [x,y]=xy(p);bg.beginPath();bg.arc(x,y,2,0,Math.PI*2);bg.fill(); }
    }
    bg.globalAlpha=1;
  }
  function cell(row, value) { const td=document.createElement('td');td.textContent=value;row.append(td);return td; }
  function render() {
    $('time').textContent=iso(current); $('seek').value=current;
    $('position-caption').textContent=`At ${iso(current)} · decimal degrees. Unknown positions are never carried forward.`;
    $('seek').setAttribute('aria-valuetext',iso(current));
    ctx.clearRect(0,0,900,500);ctx.drawImage(backdrop,0,0);
    const body=$('positions').tBodies[0];body.replaceChildren();
    for(const p of snapshot()){
      const row=body.insertRow();row.dataset.track=p.id;row.dataset.status=p.status;
      cell(row,p.alias);const status=cell(row,'');const badge=document.createElement('span');badge.className=`status ${p.status}`;badge.textContent=p.status;status.append(badge);
      cell(row,fmt(p.lat));cell(row,fmt(p.lon));cell(row,p.reason || '—');
      if(p.status==='unknown')continue;
      const [x,y]=xy(p);ctx.beginPath();ctx.arc(x,y,7,0,Math.PI*2);ctx.lineWidth=3;ctx.strokeStyle=colors[p.id%colors.length];ctx.fillStyle=p.status==='observed'?ctx.strokeStyle:'#fff';ctx.fill();ctx.stroke();
      ctx.fillStyle='#142c39';ctx.font='bold 13px system-ui';ctx.fillText(p.alias,Math.min(x+12,720),Math.max(y-10,24));
    }
    if(!selected.size){const row=body.insertRow();cell(row,'No participants selected.').colSpan=5;}
    $('previous').disabled=!visible.some(v=>v.p.t<current);
    $('next').disabled=!visible.some(v=>v.p.t>current);
  }
  function pause(){if(animation!==null)cancelAnimationFrame(animation);animation=null;playing=false;last=null;$('play').textContent='Play';$('play').setAttribute('aria-pressed','false');}
  function seek(t){pause();current=Math.max(data.start,Math.min(data.end,Math.round(t)));render();}
  function observationPage(){
    const pages=Math.max(1,Math.ceil(visible.length/50));page=Math.max(1,Math.min(page,pages));
    $('page-number').value=page;$('page-number').max=pages;$('pages').textContent=`of ${pages}`;
    $('page-prev').disabled=page===1;$('page-next').disabled=page===pages;
    $('observation-summary').textContent=`${visible.length} observations · showing ${visible.length?(page-1)*50+1:0}–${Math.min(page*50,visible.length)}`;
    const body=$('observations').tBodies[0];body.replaceChildren();
    for(const {tr,p} of visible.slice((page-1)*50,page*50)){
      const row=body.insertRow();cell(row,tr.alias);const td=cell(row,'');const button=document.createElement('button');button.textContent=iso(p.t);button.addEventListener('click',()=>seek(p.t));td.append(button);
      cell(row,fmt(p.lat));cell(row,fmt(p.lon));cell(row,`${p.location.track} / ${p.location.segment} / ${p.location.point}`);
    }
  }
  function filter(){visible=all.filter(v=>selected.has(v.tr.id));page=1;observationPage();background();render();}
  for(const tr of data.tracks){
    const label=document.createElement('label'), input=document.createElement('input'), swatch=document.createElement('span'), name=document.createElement('span');
    input.type='checkbox';input.checked=true;input.dataset.track=tr.id;swatch.className='swatch';swatch.style.background=colors[tr.id%colors.length];name.textContent=tr.alias;
    input.addEventListener('change',()=>{if(input.checked)selected.add(tr.id);else selected.delete(tr.id);filter();});label.append(input,swatch,name);$('tracks').append(label);
  }
  $('seek').min=data.start;$('seek').max=data.end;$('seek').disabled=data.start===data.end;
  $('start').textContent=iso(data.start);$('end').textContent=iso(data.end);
  $('count').textContent=`${all.length.toLocaleString('en-US')}`;const small=document.createElement('small');small.textContent='recorded, timestamped observations';$('count').append(small);
  $('gap-rule').textContent=`Interpolate only within a continuous segment, up to ${data.max_gap_ms/1000} seconds between observations. Longer intervals are unknown.`;
  $('provenance').textContent=data.tracks.map(tr=>`${tr.alias}\nSHA-256 ${tr.source.sha256}\n${tr.points.length} observations; ${tr.gaps.length} gaps; ${tr.diagnostics.length} missing times; ${tr.ignored_elements} ignored elements`).join('\n\n');
  $('seek').addEventListener('input',()=>seek(Number($('seek').value)));
  $('seek').addEventListener('keydown',event=>{let t;if(event.key==='ArrowLeft'||event.key==='ArrowDown')t=current-(event.shiftKey?10000:1000);if(event.key==='ArrowRight'||event.key==='ArrowUp')t=current+(event.shiftKey?10000:1000);if(event.key==='Home')t=data.start;if(event.key==='End')t=data.end;if(t!==undefined){event.preventDefault();seek(t);}});
  $('seek-form').addEventListener('submit',event=>{event.preventDefault();const value=$('at').value;const t=Date.parse(value);if(!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?Z$/.test(value)||!Number.isFinite(t)||iso(t).slice(0,19)!==value.slice(0,19)||t<data.start||t>data.end){$('message').textContent='Enter a valid UTC time within the timeline, ending in Z.';return;}$('message').textContent='';seek(t);});
  $('previous').addEventListener('click',()=>{const v=visible.findLast(v=>v.p.t<current);if(v)seek(v.p.t);});
  $('next').addEventListener('click',()=>{const v=visible.find(v=>v.p.t>current);if(v)seek(v.p.t);});
  $('page-prev').addEventListener('click',()=>{page--;observationPage();});$('page-next').addEventListener('click',()=>{page++;observationPage();});
  $('page-number').addEventListener('change',()=>{page=Math.trunc(Number($('page-number').value))||1;observationPage();});
  $('play').disabled=data.start===data.end;
  $('play').addEventListener('click',()=>{if(playing){pause();return;}if(current===data.end)current=data.start;playing=true;last=null;$('play').textContent='Pause';$('play').setAttribute('aria-pressed','true');animation=requestAnimationFrame(tick);});
  function tick(now){if(!playing)return;if(last!==null)current=Math.min(data.end,current+Math.round((now-last)*Number($('speed').value)));last=now;if(now-lastDraw>=66 || current===data.end){render();lastDraw=now;}if(current===data.end)pause();else animation=requestAnimationFrame(tick);}
  document.addEventListener('visibilitychange',()=>{if(document.hidden)pause();});
  function frameSVG(){
    const rows=snapshot();const svgHeight=560+rows.length*24;
    const parts=[`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 ${svgHeight}" width="900" height="${svgHeight}" role="img" aria-labelledby="title description">`,
      `<title id="title">Track / Gap — ${iso(current)}</title>`,
      `<desc id="description">Synthetic local equirectangular coordinate plot. North up; east right. Filled: observed. Ring: interpolated. Unknown: no marker. Dashed lines are assumptions. Maximum gap ${data.max_gap_ms} ms.</desc>`,
      `<metadata id="frame-data">${esc(JSON.stringify({format:'track-gap-frame',version:1,time:current,max_gap_ms:data.max_gap_ms,bounds,projection:data.projection,manifest_sha256:data.manifest_sha256,sources:data.tracks.filter(tr=>selected.has(tr.id)).map(tr=>({id:tr.id,...tr.source})),positions:rows}))}</metadata>`,
      `<rect width="900" height="${svgHeight}" fill="#f8fbfa"/>`,
      `<g font-family="sans-serif" font-size="14" fill="#142c39"><text x="24" y="25">N ↑ latitude · longitude E → · synthetic</text><text x="24" y="482">${iso(current)} · max gap ${data.max_gap_ms/1000}s · filled=observed · ring=interpolated</text>`];
    for(const tr of data.tracks){
      if(!selected.has(tr.id))continue;
      let d='';
      for(let i=0;i<tr.points.length;i++){
        const p=tr.points[i],a=tr.points[i-1],[x,y]=xy(p);
        d+=`${a && a.run===p.run && p.t-a.t<=data.max_gap_ms?'L':'M'}${number(x)},${number(y)} `;
      }
      parts.push(`<path d="${d.trim()}" fill="none" stroke="${colors[tr.id%colors.length]}" stroke-dasharray="4 5" opacity="0.45"/>`);
    }
    for(const [i,p] of rows.entries()){
      if(p.status!=='unknown'){
        const [x,y]=xy(p),color=colors[p.id%colors.length];
        parts.push(`<circle data-track="${p.id}" data-status="${p.status}" cx="${number(x)}" cy="${number(y)}" r="7" fill="${p.status==='observed'?color:'#fff'}" stroke="${color}" stroke-width="3"/>`);
      }
      parts.push(`<text x="24" y="${525+i*24}">${esc(p.alias)}: ${p.status} · ${fmt(p.lat)} N, ${fmt(p.lon)} E${p.reason?' · '+p.reason:''}</text>`);
    }
    parts.push('</g></svg>\n');return parts.join('\n');
  }
  function download(text,type,name){
    try{const blob=new Blob([text],{type});if(blob.size>8*1024*1024)throw new Error('Export exceeds 8 MiB');const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);$('message').textContent=`Downloaded ${name}`;}catch(error){$('message').textContent=`Export failed: ${error.message}`;}
  }
  $('json').addEventListener('click',()=>download(raw,'application/json','timeline.json'));
  $('svg').addEventListener('click',()=>download(frameSVG(),'image/svg+xml',`frame-${current}.svg`));
  // Read-only inspection API enables independent reproducibility checks.
  Object.defineProperty(window,'trackGap',{value:Object.freeze({snapshot:()=>({time:current,positions:snapshot()}),frameSVG}),writable:false});
  filter();
})();
