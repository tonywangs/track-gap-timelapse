/* Independent browser tests: Python oracle fixtures are read, never recomputed
   using the production position function. Playwright is verification-only. */
'use strict';
const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const {pathToFileURL}=require('node:url');
const {performance}=require('node:perf_hooks');
const {chromium}=require(process.env.TRACK_GAP_PLAYWRIGHT || 'playwright');
const root=path.resolve(process.argv[2]);
const resultPath=process.argv[3];
const records=JSON.parse(fs.readFileSync(path.join(root,'oracles.json'),'utf8'));
function compare(actual,expected,where){
  assert.equal(actual.status,expected.status,where);
  assert.equal(actual.reason,expected.reason,where);
  for(const key of ['lat','lon']){
    if(expected[key]===null)assert.equal(actual[key],null,where);
    else assert.ok(Math.abs(actual[key]-expected[key])<1e-10,`${where}: ${key} ${actual[key]} vs ${expected[key]}`);
  }
}
(async()=>{
  const began=performance.now();
  const browser=await chromium.launch({headless:true,args:['--no-sandbox','--disable-background-networking']});
  const context=await browser.newContext({acceptDownloads:true,viewport:{width:1280,height:900},offline:true});
  const external=[],errors=[];
  await context.route('**/*',route=>{
    if(route.request().url().startsWith('file:'))return route.continue();
    external.push(route.request().url());
    return route.abort();
  });
  const page=await context.newPage();
  page.on('pageerror',error=>errors.push(error.message));
  page.on('dialog',dialog=>{errors.push('unexpected dialog: '+dialog.message());dialog.dismiss();});
  let queryCount=0,positionCount=0,svgCount=0,maxRows=0;
  const open=async name=>{await page.goto(pathToFileURL(path.join(root,name,'timelapse.html')).href);await page.waitForFunction(()=>window.trackGap);};
  try{
    for(const record of records){
      await page.goto(pathToFileURL(record.html).href);
      await page.waitForFunction(()=>window.trackGap);
      const actual=await page.evaluate(queries=>{
        const seek=document.getElementById('seek');
        return queries.map((q,i)=>{
          seek.value=q.time;seek.dispatchEvent(new Event('input'));
          const snapshot=window.trackGap.snapshot();
          let frame=null;
          if(i%13===0){
            const text=window.trackGap.frameSVG();
            const xml=new DOMParser().parseFromString(text,'image/svg+xml');
            if(xml.querySelector('parsererror'))throw new Error('invalid SVG');
            frame={paths:i===0?[...xml.querySelectorAll('path')].map(p=>p.getAttribute('d')):null,table:[...document.querySelectorAll('#positions tbody tr')].map(row=>[...row.cells].map(c=>c.textContent)),caption:document.getElementById('position-caption').textContent,metadata:JSON.parse(xml.querySelector('metadata').textContent),circles:[...xml.querySelectorAll('circle')].map(c=>({id:Number(c.dataset.track),status:c.dataset.status,x:Number(c.getAttribute('cx')),y:Number(c.getAttribute('cy'))})),text:xml.documentElement.textContent,repeat:window.trackGap.frameSVG()===text};
          }
          return {snapshot,frame};
        });
      },record.queries);
      for(let i=0;i<record.queries.length;i++){
        const expected=record.queries[i],{snapshot,frame}=actual[i];
        queryCount++;assert.equal(snapshot.time,expected.time);
        assert.equal(snapshot.positions.length,expected.positions.length);
        for(let j=0;j<expected.positions.length;j++){positionCount++;compare(snapshot.positions[j],expected.positions[j],`${record.seed}/${i}/${j}`);}
        if(frame){
          svgCount++;assert.ok(frame.repeat);assert.equal(frame.metadata.time,expected.time);
          assert.match(frame.text,/North up; east right/);assert.match(frame.text,/Maximum gap/);
          for(let j=0;j<expected.positions.length;j++){
            const p=expected.positions[j];
            compare(frame.metadata.positions[j],p,`SVG ${record.seed}/${i}/${j}`);
            assert.equal(frame.table[j][1],p.status);
            assert.equal(frame.table[j][4],p.reason || '—');
            for(const [column,key] of [[2,'lat'],[3,'lon']]){
              if(p[key]===null)assert.equal(frame.table[j][column],'—');
              else assert.ok(Math.abs(Number(frame.table[j][column])-p[key])<=0.00000051);
            }
          }
          assert.ok(frame.caption.includes(new Date(expected.time).toISOString()));
          assert.equal(frame.circles.length,expected.positions.filter(p=>p.status!=='unknown').length);
          // Independently compute plot coordinates from the documented projection.
          const b=frame.metadata.bounds;
          const latitudeCenter=(b.north+b.south)/2,longitudeCenter=(b.east+b.west)/2;
          const longitudeFactor=Math.cos(latitudeCenter*Math.PI/180);
          const factor=Math.min(760/Math.max((b.east-b.west)*longitudeFactor,.0001),340/Math.max(b.north-b.south,.0001));
          if(frame.paths){
            assert.equal(frame.paths.length,record.paths.length);
            for(let j=0;j<frame.paths.length;j++){
              const vertices=frame.paths[j].split(' ').map(v=>({command:v[0],xy:v.slice(1).split(',').map(Number)}));
              assert.equal(vertices.length,record.paths[j].length);
              for(let k=0;k<vertices.length;k++){
                const v=vertices[k],p=record.paths[j][k];
                assert.equal(v.command,p.command,`SVG continuity ${record.seed}/${j}/${k}`);
                assert.ok(Math.abs(v.xy[0]-(450+(p.lon-longitudeCenter)*longitudeFactor*factor))<.000002);
                assert.ok(Math.abs(v.xy[1]-(250-(p.lat-latitudeCenter)*factor))<.000002);
              }
            }
          }
          for(const circle of frame.circles){
            const p=expected.positions[circle.id];
            assert.equal(circle.status,p.status);
            assert.ok(Math.abs(circle.x-(450+(p.lon-longitudeCenter)*longitudeFactor*factor))<.000002);
            assert.ok(Math.abs(circle.y-(250-(p.lat-latitudeCenter)*factor))<.000002);
          }
        }
      }
      maxRows=Math.max(maxRows,await page.locator('#observations tbody tr').count());
      if((record.seed+1)%80===0)console.log(`Verified ${record.seed+1} seeded browser cases.`);
    }
    await open('sample');
    // Exact seeking, invalid calendar rejection, gap semantics, standard controls.
    await page.locator('#at').fill('2025-01-01T12:00:40.000Z');
    await page.locator('#seek-form button').click();
    let snapshot=await page.evaluate(()=>window.trackGap.snapshot());
    assert.equal(snapshot.positions[0].reason,'missing-time');
    assert.equal(snapshot.positions[1].status,'interpolated');
    await page.locator('#at').fill('2025-02-30T12:00:00Z');
    await page.locator('#seek-form button').click();
    assert.match(await page.locator('#message').innerText(),/valid UTC/);
    await page.locator('#seek').focus();await page.keyboard.press('Home');
    const start=(await page.evaluate(()=>window.trackGap.snapshot())).time;
    await page.keyboard.press('ArrowRight');assert.equal((await page.evaluate(()=>window.trackGap.snapshot())).time,start+1000);
    await page.keyboard.press('Shift+ArrowRight');assert.equal((await page.evaluate(()=>window.trackGap.snapshot())).time,start+11000);
    await page.locator('#next').click();assert.equal((await page.evaluate(()=>window.trackGap.snapshot())).time,start+20000);
    await page.locator('#previous').click();assert.equal((await page.evaluate(()=>window.trackGap.snapshot())).time,start+10000);
    await page.locator('#speed').selectOption('60');await page.locator('#play').click();
    await page.waitForTimeout(180);await page.locator('#play').click();
    snapshot=await page.evaluate(()=>window.trackGap.snapshot());assert.ok(snapshot.time>start+10000);
    assert.equal(await page.locator('#play').getAttribute('aria-pressed'),'false');
    const paused=snapshot.time;await page.waitForTimeout(100);assert.equal((await page.evaluate(()=>window.trackGap.snapshot())).time,paused);
    await page.locator('#tracks input').first().focus();await page.keyboard.press('Space');
    assert.equal(await page.locator('#tracks input').first().isChecked(),false);
    assert.equal(await page.locator('#positions tbody tr').count(),1);
    assert.equal(await page.locator('#observations tbody tr').count(),6);
    // Downloads are actual browser download events, with parsed file contents.
    const jsonDownload=page.waitForEvent('download');await page.locator('#json').click();
    const downloadedJSON=JSON.parse(fs.readFileSync(await (await jsonDownload).path(),'utf8'));
    assert.deepEqual(downloadedJSON,JSON.parse(fs.readFileSync(path.join(root,'sample/timeline.json'),'utf8')));
    const svgDownload=page.waitForEvent('download');await page.locator('#svg').click();
    const svgText=fs.readFileSync(await (await svgDownload).path(),'utf8');
    const exported=await page.evaluate(text=>JSON.parse(new DOMParser().parseFromString(text,'image/svg+xml').querySelector('metadata').textContent),svgText);
    assert.equal(exported.positions.length,1);assert.equal(exported.positions[0].id,1);assert.equal(exported.time,paused);
    assert.equal(svgText,await page.evaluate(()=>window.trackGap.frameSVG()));
    await page.locator('#tracks input').last().uncheck();assert.match(await page.locator('#positions').innerText(),/No participants/);
    assert.equal(await page.locator('#observations tbody tr').count(),0);
    // Narrow viewport: controls stay in document bounds; table scroll is local.
    await page.setViewportSize({width:360,height:800});
    await page.locator('#tracks input').first().check();
    const dimensions=await page.evaluate(()=>({doc:document.documentElement.scrollWidth,width:innerWidth,buttons:[...document.querySelectorAll('button')].filter(b=>b.getClientRects().length && !b.closest('.scroll')).map(b=>({left:b.getBoundingClientRect().left,right:b.getBoundingClientRect().right}))}));
    assert.ok(dimensions.doc<=dimensions.width,JSON.stringify(dimensions));
    for(const b of dimensions.buttons)assert.ok(b.left>=0 && b.right<=360);
    await page.screenshot({path:path.join(root,'narrow.png'),fullPage:true});
    await page.setViewportSize({width:1280,height:900});
    await page.screenshot({path:path.join(root,'desktop.png'),fullPage:true});
    await open('hostile');
    assert.equal(await page.locator('img').count(),0);
    assert.match(await page.locator('#tracks').innerText(),/<\/script><img/);
    const hostile=await page.evaluate(()=>new DOMParser().parseFromString(window.trackGap.frameSVG(),'image/svg+xml').querySelector('parsererror')===null);
    assert.ok(hostile);
    await open('single');assert.ok(await page.locator('#play').isDisabled());assert.ok(await page.locator('#seek').isDisabled());
    const largeStart=performance.now();await open('large');const loadMs=performance.now()-largeStart;
    assert.equal(await page.locator('#observations tbody tr').count(),50);
    // Visit every page to prove all 20,000 records remain reachable.
    const reachability=await page.evaluate(()=>{
      const pageNumber=document.getElementById('page-number');const seen=new Set();let max=0;
      for(let p=1;p<=400;p++){
        pageNumber.value=p;pageNumber.dispatchEvent(new Event('change'));
        const rows=[...document.querySelectorAll('#observations tbody tr')];max=Math.max(max,rows.length);
        for(const row of rows)seen.add(row.cells[0].textContent+'|'+row.cells[1].textContent);
      }
      return {count:seen.size,max,dom:document.querySelectorAll('*').length};
    });
    assert.equal(reachability.count,20000);assert.equal(reachability.max,50);
    await page.locator('#observations tbody button').last().click();
    assert.equal((await page.evaluate(()=>window.trackGap.snapshot())).positions[0].status,'observed');
    assert.equal((await page.evaluate(()=>window.trackGap.snapshot())).time,1735742799000);
    const largeDownload=page.waitForEvent('download');await page.locator('#svg').click();
    const largeSVG=fs.readFileSync(await (await largeDownload).path(),'utf8');
    assert.ok(Buffer.byteLength(largeSVG)<8*1024*1024);
    const largeMetadata=await page.evaluate(text=>JSON.parse(new DOMParser().parseFromString(text,'image/svg+xml').querySelector('metadata').textContent),largeSVG);
    assert.equal(largeMetadata.positions.length,2);
    assert.equal(largeMetadata.sources.length,2);
    for(const p of largeMetadata.positions){assert.equal(p.status,'observed');assert.equal(p.lon,-109.99901);}
    assert.equal(largeMetadata.positions[0].lat,35.00099);
    assert.equal(largeMetadata.positions[1].lat,35.00019);
    assert.equal(errors.length,0,JSON.stringify(errors));assert.equal(external.length,0,JSON.stringify(external));
    const result={browser:browser.version(),playwright:require((process.env.TRACK_GAP_PLAYWRIGHT || 'playwright')+'/package.json').version,node:process.version,seeded_cases:records.length,queries:queryCount,position_comparisons:positionCount,svg_frames_checked:svgCount,svg_path_cases_checked:records.length,max_observation_rows:Math.max(maxRows,reachability.max),large_workload_observations_reached:reachability.count,large_dom_elements:reachability.dom,large_svg_bytes:Buffer.byteLength(largeSVG),large_load_ms:Math.round(loadMs),external_requests:external.length,page_errors:errors.length,elapsed_seconds:Number(((performance.now()-began)/1000).toFixed(3)),checks:['play/pause','speed','seek','keyboard','filter','pagination','narrow viewport','JSON download','SVG download','hostile alias','single observation']};
    if(resultPath)fs.writeFileSync(resultPath,JSON.stringify(result,null,2)+'\n');
    console.log(JSON.stringify(result,null,2));
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
