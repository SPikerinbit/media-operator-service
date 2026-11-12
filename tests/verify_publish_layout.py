"""Fixed publishing desk, independent scrolling and one responsive screening surface."""
import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

origin = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8846'
out = Path(sys.argv[2] if len(sys.argv) > 2 else 'data/paper-workbench-20261112/publish-layout')
out.mkdir(parents=True, exist_ok=True)
results = {'fixture_only': True, 'sizes': [], 'errors': []}

with sync_playwright() as pw:
    browser = pw.chromium.launch(channel='msedge', headless=True)
    context = browser.new_context(viewport={'width':1280, 'height':800}, record_video_dir=str(out/'video'))
    context.add_init_script("localStorage.setItem('workbench-onboarding','done')")
    page = context.new_page()
    page.on('pageerror', lambda error: results['errors'].append(str(error)))
    page.goto(origin+'/desktop/connect?token=workbench-review')

    def post(path, data):
        response = page.request.post(origin+path, data=data, headers={'Origin':origin})
        assert response.ok, response.text()
        return response.json()

    def choose(entry):
        toggle = page.locator('.publish .incoming-toggle')
        if toggle.is_visible() and toggle.get_attribute('aria-expanded') == 'false':
            toggle.click()
        page.locator(f'[data-entry-id="{entry["id"]}"] .incoming-open').click()

    def fixed():
        return page.locator('.publish.workbench-queue').evaluate('''n=>({
          machine:n.querySelector('.process-machine').getBoundingClientRect().toJSON(),
          actions:n.querySelector('.prepare-actions').getBoundingClientRect().toJSON(),
          title:n.querySelector('.letter-title').getBoundingClientRect().toJSON(),
          scroll:[document.documentElement,...[...document.querySelectorAll('#workspace,.workspace-content,.lane-view:not(.is-parked),.publish.workbench-queue,.publish .queue-desk,.publish .selected-letter')]].map(e=>[e.scrollTop,e.scrollLeft])
        })''')

    try:
        gid = post('/desktop/inbox/deliveries', {'request_id':str(time.time_ns()), 'lane':'publish', 'entries':[
            {'id':str(i),'text':f'https://example.com/video-layout-{time.time_ns()}-{i}'} for i in range(14)
        ]})['group_id']
        for _ in range(100):
            entries = [e for e in page.request.get(origin+'/desktop/inbox/queue').json()['entries'] if e['group_id']==gid]
            if len(entries)==14 and all(e['status']=='ready' for e in entries): break
            page.wait_for_timeout(100)
        assert len(entries)==14
        page.get_by_role('button', name='投稿', exact=True).click()
        page.wait_for_timeout(1100)
        choose(entries[0])
        for width,height in [(1920,1080),(1440,940),(1280,800),(1280,720),(950,680),(853,533)]:
            page.set_viewport_size({'width':width,'height':height})
            page.wait_for_timeout(300)
            page.get_by_role('button', name='设置字幕样式', exact=True).click()
            panel = page.locator('#publish-settings')
            panel.evaluate('(n)=>n.scrollTop=0')
            before = fixed()
            bounds = panel.bounding_box()
            page.mouse.move(bounds['x']+bounds['width']/2, bounds['y']+bounds['height']/2)
            page.mouse.wheel(0, 2400)
            page.wait_for_timeout(250)
            after = fixed()
            assert before == after, (width,height,before,after)
            scroll = panel.evaluate('(n)=>({top:n.scrollTop,height:n.clientHeight,total:n.scrollHeight})')
            if scroll['total']>scroll['height']+1: assert scroll['top']>0, scroll
            page.mouse.wheel(0, 2400)
            page.wait_for_timeout(100)
            assert fixed()==before, 'Scroll escaped the form panel'
            assert all(x==[0,0] for x in after['scroll']), after
            page.screenshot(path=str(out/f'form-{width}x{height}.png'))
            # Swapping tasks must not animate or move the desk or the machine.
            page.evaluate('''()=>{window.deskFrames=[];window.watchDesk=true;function frame(){if(!window.watchDesk)return;const n=document.querySelector('.publish .process-machine'),s=document.querySelector('.publish .selected-letter');window.deskFrames.push({rect:n.getBoundingClientRect().toJSON(),transform:getComputedStyle(s).transform});requestAnimationFrame(frame)}requestAnimationFrame(frame)}''')
            choose(entries[1]); page.wait_for_timeout(260); choose(entries[0]); page.wait_for_timeout(260)
            frames = page.evaluate('()=>{window.watchDesk=false;return window.deskFrames}')
            assert all(f['transform']=='none' and all(abs(f['rect'][k]-before['machine'][k])<.1 for k in ['x','y','width','height']) for f in frames), frames
            page.get_by_role('tab', name='预览', exact=True).click()
            page.wait_for_timeout(700)
            assert page.locator('.publish .desk-tv').count()==1
            assert page.locator('.publish .preview-screen').count()==0, 'Duplicate screen'
            screen=page.locator('.publish .tv-screen').bounding_box()
            bezel=page.locator('.publish .tv-bezel').bounding_box()
            assert abs(screen['width']/screen['height']-16/9)<.02,screen
            assert screen['width']>=200 and bezel['x']+bezel['width']<=width,bezel
            assert before['actions']['bottom']<=height, before
            assert page.evaluate('()=>[document.documentElement.scrollWidth,document.documentElement.scrollHeight]')==[width,height]
            page.screenshot(path=str(out/f'preview-{width}x{height}.png'))
            results['sizes'].append({'viewport':[width,height],'form_scroll':scroll,'screen':screen,'task_switch_frames':len(frames)})
        # A fully reused execution may finish in the start response; no full paper reappears.
        page.set_viewport_size({'width':1280,'height':800})
        page.get_by_role('button',name='使用当前设置备齐',exact=True).click()
        page.wait_for_timeout(2600)
        page.get_by_role('button',name='开始处理 14 条',exact=True).click()
        page.locator('.ignition-slip input').check()
        def complete(route):
            post('/fixture/state',{'id':entries[0]['id'],'status':'succeeded','execution_id':'instant-'+str(time.time_ns()),'work_progress':100,'work_progress_known':True})
            route.fulfill(status=200,json={'entry_ids':[entries[0]['id']]})
        page.route('**/desktop/inbox/groups/*/start',complete)
        page.get_by_role('button',name='确认并点火',exact=True).click()
        page.wait_for_timeout(1600)
        assert page.locator('.publish .paper-process').get_attribute('data-shown')=='1.0000'
        assert page.locator('.process-paper-flight').count()==0
        results['instant_completion']=True
        assert not results['errors'],results['errors']
    finally:
        (out/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
        context.close();browser.close()
print(json.dumps(results,ensure_ascii=False))
