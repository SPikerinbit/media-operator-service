const {chromium} = require(process.env.MEDIA_UI_PLAYWRIGHT || 'playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const out=process.argv[2];
if(!out) throw new Error('Pass an existing directory for test results');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const page=await browser.newPage({viewport:{width:1440,height:900},colorScheme:'light'});
 const errors=[]; page.on('pageerror',e=>errors.push(e.message));
 try{
 await page.goto('http://127.0.0.1:8799/desktop/connect?token=studio-review#knowledge/1');
 await page.locator('.draft').nth(99).waitFor({state:'attached'});
 assert.equal(await page.locator('.cue').count(),3000);
 const measure=()=>page.evaluate(()=>({body:document.body.scrollHeight,vh:innerHeight,workspace:document.querySelector('.workspace').scrollTop,
 source:document.querySelector('.source-pane').getBoundingClientRect().y,library:document.querySelector('.library').getBoundingClientRect().y,
 player:document.querySelector('.source-player')?.getBoundingClientRect().y,cue:document.querySelector('.cue-list').scrollTop,draft:document.querySelector('.draft-list').scrollTop,
 overflow:document.documentElement.scrollWidth>innerWidth}));
 const before=await measure();
 await page.locator('.draft-list').evaluate(e=>e.scrollTop=e.scrollHeight);
 const after=await measure();
 assert.equal(before.source,after.source);assert.equal(before.player,after.player);assert.equal(before.cue,after.cue);assert.equal(after.workspace,0);assert.ok(!after.overflow);assert.ok(after.draft>1000);
 await page.locator('.draft-list').evaluate(e=>e.scrollTop=0);
 const card=page.locator('.draft').first(); await card.locator('.edit-toggle').click();
 await card.getByLabel('主题',{exact:true}).fill('自动保存验证主题');
 await card.getByRole('status').filter({hasText:'已保存'}).waitFor();
 await page.getByRole('navigation',{name:'工作台'}).getByRole('button',{name:'设置',exact:true}).click();
 await page.getByRole('navigation',{name:'设置分类'}).getByRole('button',{name:'DeepSeek',exact:true}).click();
 await page.getByLabel('模型',{exact:true}).fill('unsaved-model-test');
 await page.getByRole('navigation',{name:'设置分类'}).getByRole('button',{name:'常规与目录'}).click();
 await page.getByRole('navigation',{name:'设置分类'}).getByRole('button',{name:'DeepSeek',exact:true}).click();
 assert.equal(await page.getByLabel('模型',{exact:true}).inputValue(),'unsaved-model-test');
 await page.getByRole('navigation',{name:'工作台'}).getByRole('button',{name:'字幕分析',exact:true}).click();
 assert.equal(await card.getByLabel('主题',{exact:true}).inputValue(),'自动保存验证主题');
 // Simulate one failed auto-save and retain the edit through material switches.
 let fail=true;
 await page.route('**/desktop/knowledge/1/cards/*',async route=>{if(route.request().method()==='PUT'&&fail){await route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'模拟保存失败'})})}else await route.continue()});
 await card.getByLabel('主题',{exact:true}).fill('失败后保留的草稿');
 await card.getByText('未保存成功',{exact:false}).waitFor();
 await page.locator('.library-list button').first().click();
 await page.getByLabel('搜索标题、字幕或观点').fill('How to remember');
 await page.locator('.library-list button').first().click();
 assert.equal(await page.locator('.draft').first().getByLabel('主题',{exact:true}).inputValue(),'失败后保留的草稿');
 fail=false;await page.getByRole('button',{name:'重试保存',exact:true}).click();
 await page.locator('.draft').first().getByRole('status').filter({hasText:'已保存'}).waitFor();
 // Citation changes only subtitle scroll and player position.
 await page.locator('.draft-list').evaluate(e=>e.scrollTop=e.scrollHeight);
 await page.locator('.draft').last().locator('.citation').first().click();
 assert.equal(await page.locator('.workspace').evaluate(e=>e.scrollTop),0);
 assert.ok(await page.locator('.cue-list').evaluate(e=>e.scrollTop)>1000);
 // All supported widths, themes and density preserve bounded panels.
 const layouts=[];
 for(const size of [[1440,900],[1280,800],[950,680],[820,1180],[768,1024],[390,844],[320,844]]){
  await page.setViewportSize({width:size[0],height:size[1]});
  await page.waitForTimeout(180);
  const x=await page.evaluate(()=>({width:innerWidth,overflow:document.documentElement.scrollWidth>innerWidth,body:document.body.scrollHeight,
    workspace:document.querySelector('.workspace').getBoundingClientRect().bottom,pane:document.querySelector('.analysis-grid').getBoundingClientRect().bottom}));
  assert.ok(!x.overflow,JSON.stringify(x)); assert.ok(x.pane<=size[1]+1,JSON.stringify(x));layouts.push(x);
 }
 await page.setViewportSize({width:950,height:680});
 await page.getByRole('button',{name:'素材',exact:true}).click();
 const dialog=page.getByRole('dialog',{name:'待分析素材'});await dialog.waitFor();
 await page.keyboard.press('Escape');await dialog.waitFor({state:'hidden'});
 assert.equal(await page.evaluate(()=>document.activeElement.textContent),'素材');
 await page.emulateMedia({colorScheme:'dark',reducedMotion:'reduce',forcedColors:'active'});
 assert.equal(await page.locator('.source-pane').isVisible(),true);
 await page.emulateMedia({colorScheme:'light',reducedMotion:'no-preference',forcedColors:'none'});
 await page.getByRole('navigation',{name:'工作台'}).getByRole('button',{name:'素材处理',exact:true}).click();
 const importActions=page.locator('.queue-import');
 async function checkImportActions(){
  for(const name of ['添加文件','粘贴链接']){
   assert.equal(await page.getByRole('button',{name,exact:true}).count(),1);
   assert.equal(await importActions.getByRole('button',{name,exact:true}).count(),1);
  }
  assert.equal(await page.locator('.queue-pane').getByLabel('并发任务',{exact:true}).count(),0);
 }
 await checkImportActions();
 await page.route('**/desktop/sources/probe', async route => {
  const {source_kind}=route.request().postDataJSON();
  await route.fulfill({json:{ready:true,title:'回归测试 · '+source_kind,media_type:'video',
    platform:source_kind,duration:20,has_audio:true,audio_direct:true}});
 });
 await page.locator('.queue-import').getByRole('button',{name:'粘贴链接',exact:true}).click();
 const douyin='https://v.douyin.com/test-share/';
 const xhs='https://xhslink.cn/o/test-share';
 await page.getByLabel('链接或分享文案').fill(
  '4.35 复制打开抖音，查看示例作品 '+douyin+
  ' 02/03 :1pm   示例笔记 '+xhs+' 复制这段话，打开【小红书】查看。');
 await page.getByRole('button',{name:'加入队列',exact:true}).click();
 await page.getByRole('dialog',{name:'粘贴素材链接'}).waitFor({state:'hidden'});
 await page.locator('.queue-row').nth(1).getByRole('slider').waitFor();
 await page.getByRole('button',{name:'处理参数',exact:true}).click();
 const inspector=page.getByRole('dialog',{name:'处理参数'});await inspector.waitFor();
 const concurrency='并发任务';
 const parallel=inspector.getByRole('region',{name:'批次执行'}).getByLabel(concurrency,{exact:true});
 assert.equal(await parallel.inputValue(),'2');
 await parallel.selectOption('4');
 await inspector.getByRole('button',{name:'当前素材',exact:true}).click();
 assert.equal(await inspector.getByLabel(concurrency,{exact:true}).count(),0);
 await inspector.getByRole('button',{name:'批次默认',exact:true}).click();
 assert.equal(await parallel.inputValue(),'4');
 await inspector.getByRole('tab',{name:'B 站投稿',exact:true}).click();
 await inspector.getByLabel('简介',{exact:true}).fill('保留的投稿简介');
 await page.keyboard.press('Escape');await inspector.waitFor({state:'hidden'});
 await page.getByRole('button',{name:'处理参数',exact:true}).click();
 await inspector.getByRole('tab',{name:'B 站投稿',exact:true}).click();
 assert.equal(await inspector.getByLabel('简介',{exact:true}).inputValue(),'保留的投稿简介');
 await page.keyboard.press('Escape');
 await inspector.waitFor({state:'hidden'});
 await page.setViewportSize({width:1440,height:900});
 await checkImportActions();
 const wide=page.getByRole('complementary',{name:'处理参数'});
 await wide.getByRole('tab',{name:'转录与输出'}).click();
 assert.equal(await wide.getByRole('region',{name:'批次执行'}).getByLabel(concurrency,{exact:true}).inputValue(),'4');
 await page.getByRole('button',{name:'历史任务',exact:true}).click();
 await page.getByLabel('批次',{exact:true}).selectOption({index:1});
 await page.locator('.task-row').nth(2).waitFor();
 assert.equal(await page.locator('.task-row').count(),3);
 await page.getByRole('button',{name:/素材队列/}).click();
 await page.getByLabel('本批默认终点',{exact:true}).selectOption('download');
 await page.route('**/desktop/batches/preflight',async route=>{
  const payload=route.request().postDataJSON();
  assert.equal(payload.batch_concurrency,4);
  await route.fulfill({json:Object.fromEntries(payload.sources.map(source=>[source.client_row_id,
    {ready:true,planned_stages:['download'],title:source.source_value}]))});
 });
 await page.route('**/ui/batches',async route=>{
  await route.fulfill({json:{batch_id:'fixture-concurrency',items:[],status:'succeeded',queued:0,running:0}});
 });
 await page.route('**/ui/batches/fixture-concurrency',async route=>{
  await route.fulfill({json:{batch_id:'fixture-concurrency',items:[],status:'succeeded',queued:0,running:0}});
 });
 const submission=page.waitForResponse(r=>r.request().method()==='POST' && r.url().endsWith('/ui/batches'));
 await page.getByRole('button',{name:'开始处理',exact:true}).click();
 const submitted=(await submission).request().postDataJSON();
 assert.equal(submitted.batch_concurrency,4);
 assert.ok(submitted.sources.every(source=>source.stop_after==='download'));
 assert.deepEqual(submitted.sources.map(source=>source.source_value),[douyin,xhs]);
 assert.deepEqual(errors,[]);
 fs.writeFileSync(out+'/interaction-results.json',JSON.stringify({passed:true,errors,layouts,independentScroll:{before,after}},null,2));
 console.log('PASS: layout, keyboard, task history, unique import actions, batch-only concurrency and download submission');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
