const {chromium}=require(process.env.MEDIA_UI_PLAYWRIGHT||'D:/dev/Media Operator 构建 0.2.5/development-tools/ui-test/node_modules/playwright');
const assert=require('node:assert/strict');const fs=require('node:fs');
const out=process.argv[2];fs.mkdirSync(out,{recursive:true});
(async()=>{
const browser=await chromium.launch({channel:'msedge',headless:true});
const context=await browser.newContext({viewport:{width:1440,height:940},colorScheme:'light',recordVideo:{dir:out,size:{width:1440,height:940}}});
const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
async function api(path,body,method='POST'){return page.evaluate(async({path,body,method})=>{const r=await fetch(path,{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});return {status:r.status,data:await r.json()}},{path,body,method})}
async function geometry(target,lane){
  return target.evaluate(async lane=>{
    const sleep=ms=>new Promise(r=>setTimeout(r,ms))
    const A=window.WorkbenchAnchors,M=window.WORKBENCH_MANIFEST
    let slotGap=999,flyGap=999,sawTear=false,foldAt=0,doneAt=0
    for(let i=0;i<90;i++){
      const station=document.querySelector('.letter-station.'+lane)
      const phase=station?.getAttribute('data-phase')
      if((phase==='fold'||phase==='seal'||phase==='insert')&&!foldAt)foldAt=performance.now()
      if(phase==='insert'||phase==='route'){
        const env=station.querySelector('.delivery-envelope').getBoundingClientRect()
        const mail=station.querySelector('.desk-mailbox').getBoundingClientRect()
        const slot=A.anchorPixels(mail,M.mailbox.anchors.slot,M.mailbox.size)
        slotGap=Math.min(slotGap,Math.hypot(env.left+env.width/2-slot.x,env.top+env.height/2-slot.y))
      }
      const fly=document.querySelector('.routing-letter'),side=document.querySelector(`[data-mail-slot="${lane}"]`)
      if(fly&&side){
        const a=fly.getBoundingClientRect(),b=side.getBoundingClientRect()
        flyGap=Math.min(flyGap,Math.hypot(a.left+a.width/2-(b.left+b.width/2),a.top+a.height/2-(b.top+b.height/2)))
      }
      if(document.querySelector('.tear-sheet'))sawTear=true
      if(foldAt&&phase==='idle'&&!document.querySelector('.routing-letter')&&performance.now()-foldAt>300)doneAt=doneAt||performance.now()
      await sleep(40)
    }
    return {slotGap,flyGap,sawTear,duration:doneAt&&foldAt?doneAt-foldAt:0}
  },lane)
}
async function woodGap(target){
  return target.evaluate(async()=>{
    const sleep=ms=>new Promise(r=>setTimeout(r,ms))
    const A=window.WorkbenchAnchors,M=window.WORKBENCH_MANIFEST
    let gap=999
    for(let i=0;i<22;i++){
      const host=document.querySelector('.fuel-brazier')
      const image=host?.querySelector('.prop:not(.foreground)')
      const node=[...document.querySelectorAll('.wood-piece')].find(el=>el.style.position==='fixed')||document.querySelector('.wood-flight')
      if(image&&node){
        const land=A.woodLanding(image.getBoundingClientRect(),M,0)
        const rect=node.getBoundingClientRect()
        gap=Math.min(gap,Math.hypot(rect.left+rect.width/2-land.x,rect.top+rect.height/2-land.y))
      }
      await sleep(40)
    }
    return gap
  })
}
async function burnSample(target,lane){
  return target.evaluate(async lane=>{
    const sleep=ms=>new Promise(r=>setTimeout(r,ms))
    const A=window.WorkbenchAnchors,M=window.WORKBENCH_MANIFEST
    const root=document.querySelector('.paper-process.'+lane)
    const machine=root.querySelector('.process-machine')
    const spec=lane==='publish'?M.brazier:M.shredder
    const anchor=lane==='publish'?spec.anchors.rim:spec.anchors.feed
    let edgeGap=999,prev=-1,back=0
    const draws0=Number(root.dataset.draws||0)
    const start=performance.now()
    while(performance.now()-start<700){
      const shown=Number(root.dataset.shown||0)
      if(prev>=0&&shown+0.02<prev)back++
      if(shown>=prev)prev=shown
      const edge=Number(root.dataset.edge)
      const point=A.anchorPixels(machine.getBoundingClientRect(),anchor,spec.size)
      if(Number.isFinite(edge))edgeGap=Math.min(edgeGap,Math.abs(edge-point.y))
      await sleep(40)
    }
    return {edgeGap,back,draws:Number(root.dataset.draws||0)-draws0,shown:Number(root.dataset.shown||0)}
  },lane)
}
const id=Date.now();
await page.goto('http://127.0.0.1:8801/desktop/connect?token=workbench-review');await page.waitForTimeout(700);
await page.screenshot({path:out+'/home-light.png'});
const rows=page.locator('.letter-station.publish input.rule-input');
await rows.nth(0).fill(`第一条视频 https://example.com/video-${id}`);
await rows.nth(1).fill(`第二条视频 https://example.com/video-b-${id}`);
await rows.nth(2).fill(`音频退回 https://example.com/audio-${id}`);
const wax=await page.locator('.letter-station.publish .wax-button').boundingBox();
assert.ok(wax&&wax.width>=60&&wax.width<=68,'wax '+JSON.stringify(wax));
assert.ok(wax.width*0.83>=52&&wax.width*0.83<=56,'wax visible '+wax.width);
const hit=await page.evaluate(()=>{
  const input=document.querySelector('.letter-station.publish .rule-input');
  const box=input.getBoundingClientRect();
  const top=document.elementFromPoint(box.left+16,box.top+box.height/2);
  const paper=document.querySelector('.letter-station.publish .writing-paper').getBoundingClientRect();
  return {input:top===input,paper:paper.width};
});
assert.equal(hit.input,true,'envelope covered the writing line');
assert.ok(hit.paper>=380&&hit.paper<=420,'paper width '+hit.paper);
await page.evaluate(()=>{window.__tear=false;new MutationObserver(()=>{if(document.querySelector('.tear-sheet'))window.__tear=true}).observe(document.body,{childList:true,subtree:true})});
await page.getByRole('button',{name:'投递投稿信件',exact:true}).click();
await page.getByText('这是音频，投稿需要视频',{exact:true}).waitFor();
assert.equal(await rows.nth(0).inputValue(),'');
const border=await rows.nth(0).evaluate(el=>getComputedStyle(el).borderTopWidth);
assert.equal(border,'0px');
const delivery=await geometry(page,'publish');
assert.ok(delivery.slotGap<42,'envelope slot '+JSON.stringify(delivery));
assert.ok(delivery.flyGap<42,'sidebar flight '+JSON.stringify(delivery));
assert.equal(delivery.sawTear||await page.evaluate(()=>window.__tear),true,'returned line should tear off the paper');
assert.ok(delivery.duration>1500&&delivery.duration<3400,'delivery timing '+JSON.stringify(delivery));
let queue=await page.evaluate(()=>fetch('/desktop/inbox/queue').then(r=>r.json()));
const groupId=queue.entries.find(e=>e.raw.includes('第一条视频')&&e.raw.includes(id)).group_id;
const members=queue.entries.filter(e=>e.group_id===groupId);
assert.equal(members.filter(e=>e.status==='ready').length,2);assert(members.every(e=>!e.batch_id));
await page.screenshot({path:out+'/home-returned.png'});
await page.getByRole('button',{name:'投稿',exact:true}).click();
const queueFit=await page.evaluate(()=>{
  const strong=document.querySelector('.incoming-letter strong');
  const list=document.querySelector('.incoming-scroll');
  const letter=strong?.closest('.incoming-letter');
  if(!strong||!list||!letter)return {missing:true};
  const previous=strong.textContent;
  strong.textContent='很长的稿件标题'.repeat(80);
  const result={scroll:list.scrollWidth-list.clientWidth,letter:letter.scrollWidth-letter.clientWidth};
  strong.textContent=previous;
  return result;
});
assert.ok(!queueFit.missing&&queueFit.scroll<=1&&queueFit.letter<=1,'queue overflow '+JSON.stringify(queueFit));
await page.getByRole('button',{name:'设置输出',exact:true}).click();
await page.getByRole('button',{name:/当前稿件/}).click();
await page.getByLabel('输出画幅',{exact:true}).selectOption('9:16');
await page.screenshot({path:out+'/publish-settings.png'});
await page.getByRole('button',{name:'保存并放入火盆'}).click();
const wood=await woodGap(page);assert.ok(wood<36,'wood landing '+wood);
await page.getByRole('button',{name:'使用当前设置备齐'}).click();
await page.getByRole('button',{name:/本次投递/}).click();
await page.waitForTimeout(450);await page.screenshot({path:out+'/publish-prepared.png'});
await page.getByRole('button',{name:/^开始处理/}).click();await page.getByRole('checkbox',{name:'我已确认素材使用权限及本次投稿信息'}).check();
await page.getByRole('button',{name:'确认并点火'}).click();
await page.locator('.paper-process.publish').waitFor();
await page.waitForFunction(()=>document.querySelector('.paper-process.publish')?.dataset.live==='1',null,{timeout:20000});
const burn=await burnSample(page,'publish');
assert.ok(burn.edgeGap<8,'flame on rim '+JSON.stringify(burn));
assert.equal(burn.back,0,'publish progress moved backward');
assert.ok(burn.draws>=12,'canvas should keep up with the display '+JSON.stringify(burn));
await page.waitForTimeout(2000);await page.screenshot({path:out+'/publish-burning.png'});
await page.getByText('投稿成功，等待审核',{exact:true}).first().waitFor({timeout:25000});
await page.screenshot({path:out+'/publish-complete.png'});
await page.waitForFunction(async gid=>{const q=await fetch('/desktop/inbox/queue').then(r=>r.json());return q.entries.filter(e=>e.group_id===gid&&e.status==='succeeded').length===2},groupId,{timeout:25000});
let succeeded=0;
for(let attempt=0;attempt<8;attempt++){
  queue=await page.evaluate(()=>fetch('/desktop/inbox/queue').then(r=>r.json()));
  succeeded=queue.entries.filter(e=>e.group_id===groupId&&e.status==='succeeded').length;
  if(succeeded===2)break;
  await page.waitForTimeout(250);
}
assert.equal(succeeded,2);
const video=page.video();await context.close();fs.renameSync(await video.path(),out+'/delivery-and-publishing.webm');
const notesContext=await browser.newContext({viewport:{width:1440,height:940},colorScheme:'light',recordVideo:{dir:out,size:{width:1440,height:940}}});
const notePage=await notesContext.newPage();notePage.on('pageerror',e=>errors.push(e.message));
await notePage.goto('http://127.0.0.1:8801/desktop/connect?token=workbench-review');
await notePage.locator('.letter-station.notes input.rule-input').first().fill(`复用已投稿内容 https://example.com/video-${id}`);
await notePage.getByRole('button',{name:'投递笔记信件'}).click();await notePage.waitForTimeout(600);
await notePage.getByRole('button',{name:'笔记',exact:true}).click();
await notePage.locator('.paper-process.notes').waitFor({timeout:10000});
await notePage.waitForFunction(()=>Number.isFinite(Number(document.querySelector('.paper-process.notes')?.dataset.edge)));
const shred=await burnSample(notePage,'notes');
assert.ok(shred.edgeGap<8,'paper meets shredder feed '+JSON.stringify(shred));
await notePage.waitForTimeout(200);await notePage.screenshot({path:out+'/notes-processing.png'});
await notePage.getByRole('button',{name:'写入 Obsidian',exact:true}).waitFor({timeout:15000});
await notePage.locator('.reuse-sheet').waitFor();
const noteQueue=await notePage.evaluate(()=>fetch('/desktop/inbox/queue').then(r=>r.json()));
const note=noteQueue.entries.find(e=>e.lane==='notes'&&e.raw.includes(id));assert.equal(note.status,'succeeded');assert(note.reuse.some(r=>r.origin_lane==='publish'));
await notePage.screenshot({path:out+'/notes-complete.png'});
for(const [width,height,theme] of [[950,680,'light'],[1440,940,'dark']]){
await notePage.setViewportSize({width,height});await notePage.emulateMedia({colorScheme:theme});await notePage.getByRole('button',{name:'信箱',exact:true}).click();await notePage.waitForTimeout(200);
assert.equal(await notePage.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);await notePage.screenshot({path:out+`/home-${width}-${theme}.png`});
if(width===950){
  await notePage.locator('.letter-station.publish input.rule-input').nth(0).fill(`窄屏视频 https://example.com/video-narrow-${id}`);
  await notePage.locator('.letter-station.publish input.rule-input').nth(1).fill(`窄屏退回 https://example.com/audio-narrow-${id}`);
  await notePage.getByRole('button',{name:'投递投稿信件',exact:true}).click();
  const narrow=await geometry(notePage,'publish');
  assert.ok(narrow.slotGap<42,'narrow slot '+JSON.stringify(narrow));
  assert.ok(narrow.flyGap<42,'narrow flight '+JSON.stringify(narrow));
  assert.equal(narrow.sawTear,true);
  await notePage.getByRole('button',{name:'投稿',exact:true}).click();
  const narrowId=await notePage.evaluate(async token=>{const q=await fetch('/desktop/inbox/queue').then(r=>r.json());return q.entries.find(e=>e.raw.includes('video-narrow-'+token)&&e.status!=='rejected').id},id);
  await notePage.locator(`[data-entry-id="${narrowId}"]`).click();
  await notePage.evaluate(async ident=>{await fetch('/fixture/state',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:ident,status:'running',progress:45,stage:'burn',message:'制作成片'})})},narrowId);
  await notePage.waitForFunction(()=>Number(document.querySelector('.paper-process.publish')?.dataset.shown)>0.2,null,{timeout:8000});
  const before=await notePage.evaluate(()=>Number(document.querySelector('.paper-process.publish').dataset.shown));
  await notePage.evaluate(async ident=>{await fetch('/fixture/state',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:ident,status:'running',progress:12,stage:'burn',message:'制作成片'})})},narrowId);
  await notePage.waitForTimeout(1500);
  const after=await notePage.evaluate(()=>Number(document.querySelector('.paper-process.publish').dataset.shown));
  assert.ok(after+0.02>=before,`progress went backwards ${before} -> ${after}`);
  const narrowBurn=await burnSample(notePage,'publish');
  assert.ok(narrowBurn.edgeGap<8,'narrow flame '+JSON.stringify(narrowBurn));
  await notePage.evaluate(async ident=>{await fetch('/fixture/state',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:ident,status:'running',progress:75,stage:'burn',message:'制作成片'})})},narrowId);
  await notePage.waitForFunction(()=>Number(document.querySelector('.paper-process.publish')?.dataset.shown)>0.7,null,{timeout:8000});
  await notePage.getByRole('button',{name:'信箱',exact:true}).click();
  await notePage.getByRole('button',{name:'投稿',exact:true}).click();
  await notePage.waitForFunction(()=>Number(document.querySelector('.paper-process.publish')?.dataset.shown)>0.7,null,{timeout:8000});
}}
await notePage.emulateMedia({reducedMotion:'reduce'});await notePage.locator('.letter-station.notes input.rule-input').first().fill('中文输入法组成的完整分享文案 https://example.com/audio-reduced-'+id);
await notePage.getByRole('button',{name:'投递笔记信件'}).click();await notePage.waitForTimeout(500);assert.equal(await notePage.locator('.routing-letter').count(),0);assert.equal(await notePage.locator('.tear-sheet').count(),0);
const noteVideo=notePage.video();await notesContext.close();fs.renameSync(await noteVideo.path(),out+'/notes-and-reuse.webm');
assert.deepEqual(errors,[]);fs.writeFileSync(out+'/ui-result.json',JSON.stringify({passed:true,errors,groupId,noteId:note.id},null,2));await browser.close();console.log('PASS delivery, rejection, no early publish, per-item override, configuration, publish, automatic notes, reuse, themes and reduced motion');
})().catch(e=>{console.error(e);process.exit(1)});
