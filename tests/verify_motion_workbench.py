"""Motion contracts against the isolated fixture; no external account or AI calls."""
import json
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

origin=sys.argv[1] if len(sys.argv)>1 else 'http://127.0.0.1:8842'
out=Path(sys.argv[2] if len(sys.argv)>2 else 'data/motion-polish-20261112/browser')
out.mkdir(parents=True,exist_ok=True)
results={'fixture_only':True,'errors':[],'delivery':[],'sizes':[]}
with sync_playwright() as pw:
    browser=pw.chromium.launch(channel='msedge',headless=True)
    ctx=browser.new_context(viewport={'width':1280,'height':800})
    ctx.add_init_script("localStorage.setItem('workbench-onboarding','done')")
    page=ctx.new_page()
    page.on('pageerror',lambda error:results['errors'].append(str(error)))
    page.goto(origin+'/desktop/connect?token=workbench-review')
    page.wait_for_timeout(900)
    def api(path,body):
        r=page.request.post(origin+path,data=body,headers={'Origin':origin})
        assert r.ok,r.text()
        return r.json()
    def queue():return page.request.get(origin+'/desktop/inbox/queue').json()
    def nav(label):
        page.get_by_role('button',name=label,exact=True).click()
        page.wait_for_timeout(1000)
    def monitor(selector):
        page.evaluate('''selector=>{window.samples=[];let start=performance.now();function frame(t){const n=document.querySelector(selector);window.samples.push({t:t-start,phase:n?.dataset.phase,fold:!!document.querySelector('.fold-sheet'),trash:document.querySelectorAll('.trash-sheet').length});window.frame=requestAnimationFrame(frame)}window.frame=requestAnimationFrame(frame)}''',selector)
    def samples():return page.evaluate('()=>{cancelAnimationFrame(window.frame);return window.samples}')
    try:
        page.screenshot(path=str(out/'home-1280.png'))
        for order in ['push-first','response-first','pause-resize']:
            async_delay=1100 if order=='push-first' else 0
            def delayed(route, _request=None, *, async_delay=async_delay):
                response=route.fetch()
                if async_delay:time.sleep(async_delay/1000)
                route.fulfill(response=response)
            page.route('**/desktop/inbox/deliveries',delayed)
            token=str(time.time_ns())
            page.locator('.letter-station.notes .rule-input').first.fill('https://example.com/audio-'+token)
            monitor('.letter-station.notes')
            page.get_by_role('button',name='投递笔记信件',exact=True).click()
            page.wait_for_function("() => document.querySelector('.letter-station.notes').dataset.phase==='fold'")
            if order=='pause-resize':
                nav('投稿')
                phase=page.locator('.letter-station.notes').get_attribute('data-phase')
                page.wait_for_timeout(500)
                assert page.locator('.letter-station.notes').get_attribute('data-phase')==phase
                assert page.locator('.fold-sheet').evaluate('(n)=>getComputedStyle(n).visibility')=='hidden'
                page.set_viewport_size({'width':1920,'height':1080})
                nav('信箱')
            else:page.screenshot(path=str(out/(order+'-fold.png')))
            page.wait_for_function("() => document.querySelector('.letter-station.notes').dataset.phase==='idle'",timeout=12000)
            recorded=samples()
            phases=[x['phase'] for i,x in enumerate(recorded) if i==0 or x['phase']!=recorded[i-1]['phase']]
            assert [p for p in phases if p in ['fold','tuck','seal','insert','route']]==['fold','tuck','seal','insert','route'],phases
            results['delivery'].append({'order':order,'phases':phases,'samples':recorded})
            page.unroute('**/desktop/inbox/deliveries',delayed)
        entry=next(e for e in queue()['entries'] if token in e['raw'])
        assert entry['status']=='ready' and not entry.get('batch_id') and not entry['result']
        nav('笔记')
        page.locator('[data-entry-id="'+entry['id']+'"] .incoming-open').click()
        page.wait_for_timeout(600)
        machine=page.locator('.notes-completion .paper-process').bounding_box()
        page.get_by_role('radio',name='摘要',exact=True).click()
        page.get_by_role('button',name='开始整理',exact=True).click()
        page.wait_for_timeout(1400)
        page.screenshot(path=str(out/'notes-processing.png'))
        for _ in range(120):
            current=next(e for e in queue()['entries'] if e['id']==entry['id'])
            if current['status']=='succeeded':break
            assert current['status'] not in ['failed','blocked'],current
            page.wait_for_timeout(150)
        else:raise AssertionError(current)
        assert current['execution_mode']=='summary'
        stable=page.locator('.notes-completion .paper-process').bounding_box()
        assert all(abs(stable[k]-machine[k])<2 for k in machine),(machine,stable)
        results['machine_stable_across_processing']=True
        transcript=current['result']['transcript_id']
        api('/fixture/cards',{'transcript_id':transcript,'count':31})
        api('/fixture/long-notes',{'transcript_id':transcript})
        api('/fixture/state',{'id':entry['id'],'batch_id':None,'status':'succeeded','result':current['result'],'title':'长标题保持两行，完整标题在选中详情。'*20})
        page.reload();page.wait_for_timeout(1000)
        page.locator('[data-entry-id="'+entry['id']+'"] .incoming-open').click()
        page.locator('.notes-completion .note-desk').wait_for()
        assert page.locator('.notes-links').count()==0
        for w,h in [(1920,1080),(1280,800),(1280,720),(853,533)]:
            page.set_viewport_size({'width':w,'height':h});page.wait_for_timeout(500)
            measures=page.evaluate('''()=>{const q=document.querySelector('.workbench-queue.notes');return Object.fromEntries(['.selected-letter','.note-desk','.note-read','.source-scroll','.incoming-letter','.paper-process.notes'].map(s=>{let n=q.querySelector(s),r=n.getBoundingClientRect();return [s,{height:r.height,top:r.top,bottom:r.bottom,client:n.clientHeight,scroll:n.scrollHeight}]}))}''')
            results['sizes'].append({'viewport':[w,h],'boxes':measures})
            assert measures['.selected-letter']['bottom']<=h+1,measures
            assert measures['.source-scroll']['height']<h and measures['.source-scroll']['scroll']>10000,measures
            assert measures['.incoming-letter']['height']<=80,measures
            start=page.get_by_role('button',name='重新整理',exact=True).bounding_box()
            assert start and start['y']+start['height']<=h, start
            page.screenshot(path=str(out/f'notes-{w}x{h}.png'))
        page.set_viewport_size({'width':1920,'height':1080});page.wait_for_timeout(300)
        cards=page.locator('.notes .shred-strip[data-card-id]')
        assert cards.count()==8
        outer=page.locator('.notes .selected-letter').evaluate('(n)=>n.scrollTop')
        cards.nth(7).click()
        assert page.locator('.notes .source-scroll').evaluate('(n)=>n.scrollTop')>0
        assert page.locator('.notes .selected-letter').evaluate('(n)=>n.scrollTop')==outer
        assert page.locator('.notes .viewpoint-slip.is-linked').count()==1
        page.get_by_role('button',name='下一组',exact=True).click();page.wait_for_timeout(250)
        assert page.locator('.notes .shred-strip[data-card-id]').count()==8
        # A push is allowed to remove the row while the HTTP response is delayed.
        def late_delete(route):
            response=route.fetch();time.sleep(.7);route.fulfill(response=response)
        page.route('**/desktop/inbox/entries/remove',late_delete)
        monitor('.letter-station.notes')
        page.locator('[data-entry-id="'+entry['id']+'"] .row-delete').click()
        page.wait_for_selector('.trash-sheet',state='attached')
        page.wait_for_timeout(400);page.screenshot(path=str(out/'trash-flight.png'))
        page.wait_for_selector('.trash-sheet',state='detached')
        assert max(x['trash'] for x in samples())>=1
        page.get_by_role('button',name='撤销删除',exact=True).click()
        page.wait_for_timeout(500)
        assert page.locator('[data-entry-id="'+entry['id']+'"] .incoming-open').get_attribute('aria-pressed')=='true'
        page.unroute('**/desktop/inbox/entries/remove',late_delete)
        # Reorganizing uses the task's selected mode after flushing manual edits.
        page.locator('.notes .viewpoint-slip').first.get_by_role('button',name='编辑',exact=True).click()
        editor=page.locator('.notes .viewpoint-slip').first.get_by_label('主题',exact=True)
        editor.fill('人工编辑：重新整理前必须保存')
        requests=[]
        page.on('request',lambda req:requests.append(req.post_data_json) if req.url.endswith('/start') else None)
        for mode,label in [('curated','精华观点'),('comprehensive','大多数观点'),('summary','摘要')]:
            page.get_by_role('radio',name=label,exact=True).click()
            count=len(requests)
            page.wait_for_timeout(120);assert len(requests)==count
            page.get_by_role('button',name='重新整理',exact=True).click()
            page.get_by_role('button',name='重新整理',exact=True).wait_for(state='visible')
            page.wait_for_timeout(400)
            assert requests[-1]['notes_mode']==mode
            assert editor.input_value()=='人工编辑：重新整理前必须保存'
        results['per_task_modes_and_edit_flush']=True
        # Failed delivery preserves the frozen text and permits retry.
        nav('信箱')
        text='https://example.com/network-failure'
        page.locator('.letter-station.publish .rule-input').first.fill(text)
        page.route('**/desktop/inbox/deliveries',lambda route:route.fulfill(status=503,json={'detail':'模拟网络故障'}))
        page.get_by_role('button',name='投递投稿信件',exact=True).click()
        page.locator('.letter-station.publish .notice.error').wait_for()
        assert page.locator('.letter-station.publish .rule-input').first.input_value()==text
        assert page.get_by_role('button',name='投递投稿信件',exact=True).is_enabled()
        page.unroute('**/desktop/inbox/deliveries')
        page.locator('.letter-station.publish .rule-input').first.fill('https://example.com/video-partial-'+str(time.time_ns()))
        page.locator('.letter-station.publish .rule-input').nth(1).fill('不是有效来源')
        page.get_by_role('button',name='投递投稿信件',exact=True).click()
        page.locator('.letter-station.publish .returned-strip').wait_for()
        page.wait_for_function("() => document.querySelector('.letter-station.publish').dataset.phase==='idle'")
        page.get_by_role('button',name='恢复编辑',exact=True).click();page.wait_for_timeout(300)
        assert '不是有效来源' in page.locator('.letter-station.publish .rule-input').evaluate_all('(ns)=>ns.map(n=>n.value)')
        results['network_restore_and_partial_return']=True
        # Both lanes, a four-letter batch, three simultaneous balls, partial failure.
        for lane,label in [('publish','投稿'),('notes','笔记')]:
            gid=api('/desktop/inbox/deliveries',{'request_id':'bulk-'+str(time.time_ns()),'lane':lane,'entries':[{'id':str(i),'text':'https://example.com/video-bulk-'+str(time.time_ns())} for i in range(4)]})['group_id']
            page.wait_for_timeout(600)
            targets=[e for e in queue()['entries'] if e['group_id']==gid]
            nav(label)
            for target in targets:page.locator('[data-entry-id="'+target['id']+'"] input[type=checkbox]').check()
            failed=targets[0]['id']
            def partial(route, _request=None, *, failed=failed):
                body=route.request.post_data_json
                response=route.fetch(post_data=json.dumps({'ids':[i for i in body['ids'] if i!=failed]}))
                payload=response.json();payload['results'].append({'id':failed,'ok':False,'message':'模拟任务已开始，暂不能删除'})
                route.fulfill(response=response,json=payload)
            page.route('**/desktop/inbox/entries/remove',partial)
            monitor('.letter-station.notes')
            page.get_by_role('button',name='删除所选 4 封',exact=True).click()
            page.wait_for_selector('.trash-sheet',state='attached');page.wait_for_selector('.trash-sheet',state='detached')
            captures=samples()
            assert max(x['trash'] for x in captures)==3
            assert page.locator('[data-entry-id="'+failed+'"] .incoming-open').count()==1
            page.unroute('**/desktop/inbox/entries/remove',partial)
            page.get_by_role('button',name='撤销删除',exact=True).click();page.wait_for_timeout(500)
            assert all(next(e for e in queue()['entries'] if e['id']==target['id'])['status']!='removed' for target in targets)
            # Cancel a flight by switching desks; no unresolved promise or orphan node.
            page.locator('[data-entry-id="'+targets[1]['id']+'"] .row-delete').click()
            page.wait_for_selector('.trash-sheet',state='attached');nav('信箱')
            assert page.locator('.trash-sheet').count()==0
            nav(label)
            page.get_by_role('button',name='撤销删除',exact=True).click();page.wait_for_timeout(300)
            assert page.locator('.workbench-queue.'+lane+' .row-delete:enabled').count()>0
        # Publishing keeps its wood, brazier, paper handoff and fixed log area.
        gid=api('/desktop/inbox/deliveries',{'request_id':'hearth-'+str(time.time_ns()),'lane':'publish','entries':[{'id':'hearth','text':'https://example.com/video-hearth-'+str(time.time_ns())}]})['group_id']
        page.wait_for_timeout(600);target=next(e for e in queue()['entries'] if e['group_id']==gid)
        nav('投稿');page.locator('[data-entry-id="'+target['id']+'"] .incoming-open').click();page.wait_for_timeout(350)
        page.get_by_role('button',name='使用当前设置备齐',exact=True).click()
        page.wait_for_selector('.wood-flight',state='attached');page.wait_for_selector('.wood-flight',state='detached')
        page.get_by_role('button',name='开始处理',exact=True).click()
        page.get_by_role('checkbox',name='我已确认素材使用权限及本次投稿信息',exact=True).check()
        page.get_by_role('button',name='确认并点火',exact=True).click()
        page.wait_for_selector('.paper-process.publish[data-burning="1"]')
        page.screenshot(path=str(out/'publishing-burning.png'))
        before=page.locator('.publish .process-description').bounding_box()
        page.locator('.publish .process-description').get_by_role('button',name='查看详情',exact=True).click()
        after=page.locator('.publish .process-description').bounding_box()
        assert all(abs(before[k]-after[k])<1 for k in before),(before,after)
        results['publishing_wood_ignition_log']=True
        results['batch_partial_failure_and_page_cancel']=True
        nav('信箱');page.emulate_media(reduced_motion='reduce')
        page.locator('.letter-station.notes .rule-input').first.fill('https://example.com/audio-reduced-'+str(time.time_ns()))
        page.get_by_role('button',name='投递笔记信件',exact=True).click()
        page.wait_for_function("() => document.querySelector('.letter-station.notes').dataset.phase==='idle'")
        assert page.locator('.fold-sheet').count()==0
        results['reduced_motion']=True
        results['delete_race_and_undo']=True
        results['machine_before_start']=machine
        results['ok']=not results['errors']
    except Exception as error:
        results['ok']=False;results['failure']=str(error)
        page.screenshot(path=str(out/'failure.png'))
        raise
    finally:
        (out/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in results.items() if k not in ['delivery','sizes']},ensure_ascii=False))
        browser.close()

