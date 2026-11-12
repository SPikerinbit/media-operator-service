"""Pixel and layout contracts on the isolated workbench fixture (never live accounts)."""
import base64
import json
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

origin = sys.argv[1] if len(sys.argv)>1 else 'http://127.0.0.1:8846'
out = Path(sys.argv[2] if len(sys.argv)>2 else 'data/paper-workbench-20261112/browser')
out.mkdir(parents=True,exist_ok=True)
results={'fixture_only':True,'sizes':[],'paper':{},'handoffs':{},'errors':[]}
pixel_probe = r"""lane=>{
 const root=document.querySelector('.paper-process.'+lane),c=root.querySelector('.process-paper'),r=c.getBoundingClientRect(),m=root.querySelector('.process-machine').getBoundingClientRect();
 const edge=(m.top-r.top)+(lane==='publish'?.482*m.height:.23002*m.height);
 const d=c.getContext('2d').getImageData(0,0,c.width,c.height),sx=r.width/c.width,sy=r.height/c.height;
 let n=0,minY=c.height,maxY=-1,minX=c.width,maxX=-1;
 for(let y=0;y<Math.min(c.height,edge/sy);y++)for(let x=0;x<c.width;x++)if(d.data[(y*c.width+x)*4+3]>100){n++;minY=Math.min(y,minY);maxY=Math.max(y,maxY);minX=Math.min(x,minX);maxX=Math.max(x,maxX)}
 return {n,top:r.top+minY*sy,bottom:r.top+(maxY+1)*sy,left:r.left+minX*sx,right:r.left+(maxX+1)*sx,height:(maxY-minY+1)*sy,url:c.toDataURL(),shown:root.dataset.shown,emitted:root.dataset.emitted,fragments:root.dataset.fragments};
}"""
with sync_playwright() as pw:
 browser=pw.chromium.launch(channel='msedge',headless=True)
 context=browser.new_context(viewport={'width':1280,'height':800},record_video_dir=str(out/'video'),record_video_size={'width':1280,'height':800})
 page=context.new_page();page.on('pageerror',lambda e:results['errors'].append(str(e)))
 page.goto(origin+'/desktop/connect?token=workbench-review')
 page.request.put(origin+'/desktop/settings',data={'onboarding_complete':True},headers={'Origin':origin});page.reload();page.wait_for_timeout(600)
 def post(path,body):
  r=page.request.post(origin+path,data=body,headers={'Origin':origin});assert r.ok,r.text();return r.json()
 def queue():return page.request.get(origin+'/desktop/inbox/queue').json()
 def fixture(entry,**values):
  post('/fixture/state',{'id':entry['id'],**values});page.wait_for_timeout(800)
 def select(entry,lane):
  page.get_by_role('button',name='投稿' if lane=='publish' else '笔记',exact=True).click();page.wait_for_timeout(600)
  toggle=page.locator('.'+lane+' .incoming-toggle')
  if toggle.is_visible() and toggle.get_attribute('aria-expanded')=='false':toggle.click()
  page.locator('[data-entry-id="'+entry['id']+'"] .incoming-open').click();page.wait_for_timeout(300)
 def deliver(lane):
  gid=post('/desktop/inbox/deliveries',{'request_id':lane+str(time.time_ns()),'lane':lane,'entries':[{'id':'one','text':'https://example.com/video-'+str(time.time_ns())}]})['group_id']
  for _ in range(40):
   entry=next(e for e in queue()['entries'] if e['group_id']==gid)
   if entry['status']=='ready':return entry
   page.wait_for_timeout(100)
  raise AssertionError(entry)
 try:
  for lane in ['publish','notes']:
   page.set_viewport_size({'width':1280,'height':800})
   entry=deliver(lane);select(entry,lane)
   fixture(entry,status='running',stage='transcribe',execution_id='pixels-'+lane,work_progress=0,work_progress_known=True,
           reuse=[{'stage':'transcribe','origin_lane':'notes' if lane=='publish' else 'publish'}])
   marks=[]
   for progress in [0,5,25,50,75,99]:
    fixture(entry,work_progress=progress)
    page.wait_for_timeout(1400)
    pixels=page.evaluate(pixel_probe,lane)
    assert pixels['n']>0,(lane,progress,pixels)
    marks.append({'progress':progress,**{k:v for k,v in pixels.items() if k!='url'}})
    (out/f'{lane}-{progress}-paper.png').write_bytes(base64.b64decode(pixels['url'].split(',')[1]))
    page.screenshot(path=str(out/f'{lane}-{progress}.png'))
    if progress==5:
     before=pixels['url'];page.wait_for_timeout(10500)
     assert page.evaluate(pixel_probe,lane)['url']==before,'Paper changed while progress was stalled'
   assert all(a['height']>b['height'] for a,b in zip(marks,marks[1:])),marks
   results['paper'][lane]=marks
   before=page.evaluate(pixel_probe,lane)['url']
   fixture(entry,status='failed');page.wait_for_timeout(1000)
   assert page.evaluate(pixel_probe,lane)['url']==before,'Failure consumed the remaining paper'
   fixture(entry,status='succeeded',work_progress=100);page.wait_for_timeout(1600)
   assert page.evaluate(pixel_probe,lane)['n']==0,'Success left paper above the blade/bowl'
   # Restart resets only through a new execution id. A shared wait must not produce output.
   fixture(entry,status='running',stage='extract',execution_id='wait-'+lane,work_progress=25,waiting_for_shared=True)
   page.wait_for_timeout(1300);before=page.evaluate(pixel_probe,lane)
   page.wait_for_timeout(2500);after=page.evaluate(pixel_probe,lane)
   assert before['url']==after['url'] and after['fragments']=='0'
   # Same execution never rewinds under out-of-order updates.
   fixture(entry,work_progress=5)
   assert float(page.evaluate(pixel_probe,lane)['shown'])>=.249
   for w,h in [(1920,1080),(1440,940),(1280,800),(1280,720),(950,680),(853,533)]:
    page.set_viewport_size({'width':w,'height':h});page.wait_for_timeout(350)
    measurements=page.locator('.workbench-queue.'+lane).evaluate("""n=>{const r=n.querySelector('.selected-letter'),p=n.querySelector('.paper-process');return {outer:[document.documentElement.scrollWidth,document.documentElement.scrollHeight],selected:[r.clientWidth,r.scrollWidth,r.clientHeight,r.scrollHeight],paper:p.getBoundingClientRect().toJSON(),buttons:[...n.querySelectorAll('.prepare-actions button,.notes-plaque>.button-press-motion')].filter(b=>b.getBoundingClientRect().width).map(b=>b.getBoundingClientRect().toJSON())}}""")
    assert measurements['outer']==[w,h],measurements
    assert measurements['selected'][1]<=measurements['selected'][0]+1 and measurements['selected'][3]<=measurements['selected'][2]+1,measurements
    assert all(b['bottom']<=h+1 for b in measurements['buttons']),measurements
    results['sizes'].append({'lane':lane,'viewport':[w,h],**measurements})
    page.screenshot(path=str(out/f'{lane}-{w}x{h}.png'))
  # Geometry at handoff is measured from real canvas pixels, at 0% queued progress.
  for lane in ['publish','notes']:
   page.set_viewport_size({'width':1280,'height':800});entry=deliver(lane);select(entry,lane)
   if lane=='publish':
    page.get_by_role('button',name='使用当前设置备齐',exact=True).click();page.wait_for_timeout(2600)
    page.get_by_role('button',name='开始处理',exact=True).click()
    page.locator('.ignition-slip input[type=checkbox]').check()
   def accept(route,_request=None,*,entry=entry,lane=lane):
    post('/fixture/state',{'id':entry['id'],'status':'queued','stage':'queued','execution_id':'flight-'+lane,'work_progress':0,'work_progress_known':True})
    route.fulfill(status=200,json={'entry_ids':[entry['id']]})
   page.route('**/desktop/inbox/groups/*/start',accept)
   page.evaluate("""lane=>{window.paperFrames=[];window.capturePaper=true;function frame(){if(!window.capturePaper)return;const f=document.querySelector('.process-paper-flight'),p=document.querySelector('.paper-process.'+lane),c=p?.querySelector('.process-paper');let count=0;if(c){const d=c.getContext('2d').getImageData(0,0,c.width,c.height).data;for(let i=3;i<d.length;i+=4)if(d[i]>100)count++}window.paperFrames.push({t:performance.now(),flight:f?.getBoundingClientRect().toJSON(),count,arrived:p?.dataset.arrived});requestAnimationFrame(frame)}requestAnimationFrame(frame)}""",lane)
   page.get_by_role('button',name='确认并点火' if lane=='publish' else '开始整理',exact=True).click()
   page.wait_for_timeout(2100)
   frames=page.evaluate('()=>{window.capturePaper=false;return window.paperFrames}')
   flying=[(i,f) for i,f in enumerate(frames) if f.get('flight')]
   assert len(flying)>10,(lane,frames)
   end,last=flying[-1];landed=frames[end+1]
   assert landed['count']>0 and not landed.get('flight'),(lane,frames[end-1:end+3])
   assert all(f['count']==0 for _,f in flying),'Two sheets were visible during the flight'
   pixels=page.evaluate(pixel_probe,lane);rect=last['flight']
   error=max(abs(rect['x']-pixels['left']),abs(rect['y']-pixels['top']),abs(rect['right']-pixels['right']),abs(rect['bottom']-pixels['bottom']))
   assert error<=2,(lane,error,rect,{k:v for k,v in pixels.items() if k!='url'})
   results['handoffs'][lane]={'error_css_px':error,'frames':frames}
   page.unroute('**/desktop/inbox/groups/*/start',accept)
  assert not results['errors'],results['errors']
 finally:
  (out/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
  context.close();browser.close()
print(json.dumps({'sizes':len(results['sizes']),'handoffs':{k:v['error_css_px'] for k,v in results['handoffs'].items()},'errors':results['errors']}))
