"""Explicit browser regression, against workbench_ui_server.py only.

Run with a Python environment containing Playwright and an installed Edge:
python tests/verify_workbench_ui.py http://127.0.0.1:8832 data/ui-verification
Fixture data proves UI behavior, never external publishing or AI output quality.
"""
import json
from pathlib import Path
import sys
import time

from playwright.sync_api import expect, sync_playwright

origin = sys.argv[1]
out = Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
results = {'modes': [], 'matrix': [], 'errors': [], 'fixture_only': True}

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(channel='msedge', headless=True)
    context = browser.new_context(viewport={'width': 1920, 'height': 1080})
    page = context.new_page()
    page.on('pageerror', lambda error: results['errors'].append(str(error)))
    page.goto(origin + '/desktop/connect?token=workbench-review')
    reset = page.request.put(origin+'/desktop/settings',data={'onboarding_complete':False},headers={'Origin':origin})
    assert reset.ok
    page.reload()
    guide = page.locator('dialog.onboarding')
    guide.wait_for(state='visible')
    assert guide.locator('.setup-accounts li').count() == 4
    assert page.locator('.home-view').get_attribute('inert') is not None
    page.get_by_role('button', name='以后再说', exact=True).click()
    guide.wait_for(state='detached')
    for _ in range(20):
        if page.request.get(origin+'/desktop/settings').json().get('onboarding_complete'):
            break
        page.wait_for_timeout(100)
    else:
        raise AssertionError('Guide completion was not persisted')
    fresh = browser.new_context()
    fresh_page = fresh.new_page()
    fresh_page.goto(origin+'/desktop/connect?token=workbench-review')
    fresh_page.wait_for_timeout(600)
    assert fresh_page.locator('dialog.onboarding').count() == 0
    fresh.close()
    results['onboarding_persists_with_empty_browser_storage'] = True

    def api(path, body):
        response = page.request.post(origin + path, data=body, headers={'Origin': origin})
        assert response.ok, response.text()
        return response.json()

    token = str(time.time_ns())
    delivery = api('/desktop/inbox/deliveries', {
        'request_id': 'ui-notes-' + token, 'lane': 'notes', 'notes_mode': 'summary',
        'entries': [{'id': 'one', 'text': 'https://example.com/audio-' + token}],
    })
    group = delivery['group_id']
    for _ in range(120):
        entry = next(item for item in page.request.get(origin+'/desktop/inbox/queue').json()['entries'] if item['group_id'] == group)
        if entry['status'] == 'ready':
            api('/desktop/inbox/groups/'+group+'/start', {'revision':0,'confirmed':True,'entry_ids':[entry['id']],'notes_mode':'summary'})
        if entry['status'] == 'succeeded' and entry.get('result', {}).get('transcript_id'):
            break
        assert entry['status'] not in {'failed', 'blocked', 'rejected'}, entry
        page.wait_for_timeout(250)
    else:
        raise AssertionError(entry)
    transcript = entry['result']['transcript_id']
    api('/fixture/cards', {'transcript_id': transcript, 'count': 4})
    publish_group = api('/desktop/inbox/deliveries', {
        'request_id': 'ui-publish-' + token, 'lane': 'publish',
        'entries': [{'id':'publish', 'text':'https://example.com/video-config-'+token}],
    })['group_id']
    for _ in range(40):
        publish_entry = next(item for item in page.request.get(origin+'/desktop/inbox/queue').json()['entries'] if item['group_id'] == publish_group)
        if publish_entry['status'] == 'ready':
            break
        page.wait_for_timeout(100)
    assert publish_entry['status'] == 'ready'
    page.reload()
    page.get_by_role('button', name='投稿', exact=True).click()
    page.locator('[data-entry-id="'+publish_entry['id']+'"] .incoming-open').click()
    page.get_by_role('button', name='笔记', exact=True).click()
    page.locator('[data-entry-id="'+entry['id']+'"] .incoming-open').click()
    page.locator('.notes-completion .viewpoint-slip').first.wait_for()
    page.wait_for_timeout(1100)
    generate_requests = []
    page.on('request', lambda request: generate_requests.append(request.post_data_json)
            if request.url.endswith('/start') else None)
    for mode, label in [('summary', '摘要'), ('curated', '精华观点'), ('comprehensive', '大多数观点')]:
        before = len(generate_requests)
        page.locator('.shredder-station').get_by_role('radio', name=label, exact=True).click()
        page.wait_for_timeout(100)
        assert len(generate_requests) == before, 'Changing mode must not generate'
        with page.expect_response('**/inbox/groups/*/start') as pending:
            page.get_by_role('button', name='重新整理', exact=True).click()
        assert pending.value.ok
        assert generate_requests[-1]['notes_mode'] == mode
        results['modes'].append(generate_requests[-1])
        page.get_by_role('button',name='重新整理',exact=True).wait_for(state='visible')
    radio = page.locator('.shredder-station').get_by_role('radio', name='大多数观点', exact=True)
    page.get_by_role('button',name='重新整理',exact=True).wait_for(state='visible')
    expect(radio).to_be_enabled(timeout=30000)
    radio.focus()
    page.keyboard.press('ArrowRight')
    expect(page.locator('.shredder-station').get_by_role('radio', name='摘要', exact=True)).to_have_attribute('aria-checked', 'true')

    page.locator('.viewpoint-slip .slip-body').first.click()
    assert page.locator('.note-read .sentence[aria-pressed="true"]').count() == 1
    page.locator('.viewpoint-slip').first.get_by_role('button', name='编辑', exact=True).click()
    editor = page.locator('.viewpoint-slip').first.get_by_label('主题', exact=True)
    editor.fill('人工编辑保持不变')
    with page.expect_response('**/inbox/groups/*/start'):
        page.get_by_role('button', name='重新整理', exact=True).click()
    assert editor.input_value() == '人工编辑保持不变'

    for width, height, dpr in [(2560, 1392, 1.5), (1920, 1080, 1), (1440, 940, 1),
                               (1280, 800, 1), (1280, 720, 1.5), (1100, 700, 1),
                               (1000, 650, 1), (950, 680, 1), (900, 600, 1), (853, 533, 1.5), (720, 533, 1.5)]:
        # Viewport sizes represent logical pixels; actual OS scaling is a separate acceptance item.
        page.set_viewport_size({'width': width, 'height': height})
        for view, label in [('home', '信箱'), ('publish', '投稿'), ('notes', '笔记'), ('settings', '设置')]:
            page.get_by_role('button', name=label, exact=True).click()
            page.wait_for_timeout(1050)
            current = page.locator('main[data-view="'+view+'"]')
            assert current.count() == 1
            assert not page.locator('.is-deck-in,.is-deck-out').count(), 'Navigation animation not cleaned up'
            metrics = page.evaluate("""() => {
              const main=document.querySelector('main');
              const selected=main.querySelector('.lane-view:not([inert]) .selected-letter');
              const box=selected?.getBoundingClientRect();
              return {documentOverflow:document.documentElement.scrollWidth-innerWidth,
                contentOverflow:selected?selected.scrollWidth-selected.clientWidth:0,
                selectedWidth:box?.width||null,
                inactiveFocusable:[...main.querySelectorAll('.is-parked')].some(el=>!el.inert||el.getAttribute('aria-hidden')!=='true')};
            }""")
            assert metrics['documentOverflow'] <= 1, (width, view, metrics)
            assert metrics['contentOverflow'] <= 1, (width, view, metrics)
            assert not metrics['inactiveFocusable']
            if view == 'notes':
                tabs = page.locator('.note-panel-tabs')
                if tabs.is_visible():
                    tabs.get_by_role('button', name='原文', exact=True).click()
                source = page.locator('.note-read')
                assert source.bounding_box()['width'] >= 220
                export = source.get_by_role('button', name='导出 Markdown', exact=True)
                export.scroll_into_view_if_needed()
                assert export.bounding_box()['y'] + export.bounding_box()['height'] <= height + 1
                if tabs.is_visible():
                    tabs.get_by_role('button', name='观点', exact=True).click()
                    page.get_by_role('button', name='重新整理', exact=True).scroll_into_view_if_needed()
                tray = page.locator('.strip-tray')
                assert tray.count() == 1
                assert tray.evaluate('(el)=>el.getBoundingClientRect().right<=el.parentElement.getBoundingClientRect().right+1')
            if view == 'publish':
                if not page.get_by_role('button', name='保存并放入火盆', exact=True).count():
                    page.get_by_role('button', name='设置输出', exact=True).click()
                save = page.get_by_role('button', name='保存并放入火盆', exact=True)
                save.scroll_into_view_if_needed()
                assert save.bounding_box()['x'] + save.bounding_box()['width'] <= width + 1
                assert page.locator('.lane-view:not([inert]) .selected-letter').evaluate('(el)=>el.scrollWidth-el.clientWidth') <= 1
            page.screenshot(path=str(out/f'{width}x{height}-{view}.png'))
            results['matrix'].append({'width': width, 'height': height, 'scenario_scale': dpr, 'actual_browser_dpr': page.evaluate('() => devicePixelRatio'), 'view': view, **metrics})

    page.set_viewport_size({'width': 1440, 'height': 940})
    page.get_by_role('button', name='信箱', exact=True).click()
    page.wait_for_timeout(1100)
    assert page.locator('.home-mode').count() == 0
    page.locator('.letter-station.publish input.rule-input').first.fill('https://example.com/video-'+token)
    page.get_by_role('button', name='投递投稿信件', exact=True).click()
    page.wait_for_function("() => document.querySelector('.letter-station.publish').dataset.phase==='fold'")
    page.wait_for_timeout(430)
    hinge = page.locator('.letter-station.publish').evaluate('''el => {
      const envelope=el.querySelector('.delivery-envelope:not(.delivery-placeholder)').getBoundingClientRect();
      const back=el.querySelector('.flap-lining').getBoundingClientRect();
      return {gap:Math.abs(envelope.top-back.top),height:envelope.height}
    }''')
    assert hinge['gap'] < 2, ('Open flap detached from its hinge',hinge)
    results['open_flap_hinge'] = hinge
    page.set_viewport_size({'width': 1280, 'height': 800})
    page.wait_for_function("() => document.querySelector('.letter-station.publish').dataset.phase==='idle'")
    assert page.locator('.fold-sheet,.routing-letter,.cast-shadow').count() == 0
    assert page.locator('.letter-station.publish').get_attribute('data-phase') == 'idle'
    page.emulate_media(reduced_motion='reduce')
    page.get_by_role('button', name='设置', exact=True).click()
    page.wait_for_timeout(100)
    assert page.locator('.is-deck-in,.is-deck-out').count() == 0
    assert not results['errors'], results['errors']
    browser.close()

(out/'ui-results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
print(f"PASS: three mode payloads, keyboard, edits, {len(results['matrix'])} layouts, focus, resize cleanup, reduced motion")
