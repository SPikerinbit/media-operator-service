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
    assert page.locator('.home-view').get_attribute('inert') is not None
    page.screenshot(path=str(out/'onboarding-step1-welcome.png'))
    # Step 2: interactive 3-scene workflow demo
    guide.get_by_role('button', name='看 3 步动态演示', exact=True).click()
    guide.get_by_role('tab', name='② 添柴点火 投稿成片').click()
    page.wait_for_timeout(280)
    page.screenshot(path=str(out/'onboarding-step2-demo.png'))
    guide.get_by_role('tab', name='③ 拨档整理 知识笔记').click()
    page.wait_for_timeout(140)
    # Step 3: start background model download and immediately advance without blocking
    guide.get_by_role('button', name='下一步：准备转录模型', exact=True).click()
    guide.locator('.setup-model-card').first.wait_for(state='visible')
    page.wait_for_timeout(260)
    page.screenshot(path=str(out/'onboarding-step3-model.png'))
    guide.get_by_role('button', name='后台下载并继续', exact=True).click()
    # Immediately reaches Step 4 (Accounts + AI) with header background download pill visible and zero skip lock-in
    guide.locator('.setup-accounts li').first.wait_for(state='visible')
    assert guide.locator('.setup-accounts li').count() == 4
    guide.locator('.setup-bg-pill').wait_for(state='visible')
    page.wait_for_timeout(240)
    page.screenshot(path=str(out/'onboarding-step4-connect.png'))
    # Step 5: Ready & close into live desk with 3-step coachmarks + non-blocking background banner
    guide.get_by_role('button', name='下一步：启封开用', exact=True).click()
    guide.locator('.setup-ready li').first.wait_for(state='visible')
    page.wait_for_timeout(260)
    page.screenshot(path=str(out/'onboarding-step5-ready.png'))
    guide.get_by_role('button', name='合上手册，开始使用', exact=True).click()
    guide.wait_for(state='detached')
    # Live-desk 3-step coachmarks appear and stay strictly within viewport
    page.locator('.coachmark-card').wait_for(state='visible', timeout=5000)
    page.wait_for_timeout(340)
    page.screenshot(path=str(out/'desk-coachmark-step1.png'))
    for step_idx in range(3):
        box = page.locator('.coachmark-card').bounding_box()
        assert box and box['x'] >= 0 and box['y'] >= 0 and box['x'] + box['width'] <= 1920 and box['y'] + box['height'] <= 1080, (step_idx, box)
        if step_idx < 2:
            page.locator('.coachmark-card').get_by_role('button', name='下一步', exact=True).click()
            page.wait_for_timeout(180)
        else:
            page.locator('.coachmark-card').get_by_role('button', name='知道了，开始用', exact=True).click()
    page.locator('.coachmark-card').wait_for(state='detached')
    # Background model download continues and completes cleanly inside the app
    page.locator('.bg-model-banner.is-done').wait_for(state='visible', timeout=8000)
    page.screenshot(path=str(out/'bg-model-download-done.png'))
    results['non_blocking_model_download_and_coachmarks'] = True
    # Reopen from sidebar quick help button and dismiss via 以后再说
    page.get_by_role('button', name='打开使用教程', exact=True).click()
    guide.wait_for(state='visible')
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
    api('/fixture/summary-tree', {'transcript_id': transcript})
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
    for mode, label in [('summary', '摘要'), ('curated', '核心观点'), ('comprehensive', '大多数观点')]:
        before = len(generate_requests)
        page.locator('.shredder-station').get_by_role('radio', name=label, exact=True).click()
        page.wait_for_timeout(100)
        assert len(generate_requests) == before, 'Changing mode must not generate'
        with page.expect_response('**/inbox/groups/*/start') as pending:
            page.get_by_role('button', name='重新整理', exact=True).click()
        assert pending.value.ok, (mode, pending.value.status, pending.value.text())
        assert generate_requests[-1]['notes_mode'] == mode
        results['modes'].append(generate_requests[-1])
        page.get_by_role('button',name='重新整理',exact=True).wait_for(state='visible')
    radio = page.locator('.shredder-station').get_by_role('radio', name='大多数观点', exact=True)
    page.get_by_role('button',name='重新整理',exact=True).wait_for(state='visible')
    expect(radio).to_be_enabled(timeout=30000)
    radio.focus()
    page.keyboard.press('ArrowRight')
    expect(page.locator('.shredder-station').get_by_role('radio', name='摘要', exact=True)).to_have_attribute('aria-checked', 'true')

    # Verify unified 4-icon sidebar (no legacy brass .sidebar-mail-slot)
    assert page.locator('.sidebar-mail-slot').count() == 0
    icon_boxes = page.locator('.sidebar .nav-icon').evaluate_all('(els)=>els.map(e=>e.getBoundingClientRect())')
    assert len(icon_boxes) == 4
    assert all(abs(b['width'] - icon_boxes[0]['width']) < 1 and abs(b['height'] - icon_boxes[0]['height']) < 1 for b in icon_boxes)

    # Verify Publish vs Notes left-station geometric alignment at 1920x1080
    page.get_by_role('button', name='投稿', exact=True).click()
    page.wait_for_timeout(1100)
    pub_station = page.locator('.publish-station').bounding_box()
    pub_scene = page.locator('.publish-scene').bounding_box()
    page.get_by_role('button', name='笔记', exact=True).click()
    page.wait_for_timeout(1100)
    note_station = page.locator('.shredder-station').bounding_box()
    note_scene = page.locator('.notes-scene').bounding_box()
    assert abs(pub_station['width'] - note_station['width']) <= 2, (pub_station, note_station)
    assert abs(pub_scene['height'] - note_scene['height']) <= 2, (pub_scene, note_scene)

    # Verify 整理 / 原文 / 记录 tabs & 摘要 tree view + 核心观点 list switching
    assert '整理' in page.locator('#tab-notes-drafts').inner_text()
    assert '原文' in page.locator('#tab-notes-source').inner_text() and '译文' not in page.locator('#tab-notes-source').inner_text()
    page.locator('.organize-mode-bar').get_by_role('tab', name='摘要').click()
    page.locator('.summary-tree-pane .tree-node').first.wait_for()
    page.locator('.summary-tree-pane .tree-toggle-btn').first.click()
    page.locator('.summary-tree-pane .tree-branch-children').first.wait_for()
    page.locator('.summary-tree-pane .tree-branch-children .tree-toggle-btn').first.click()
    page.wait_for_timeout(150)
    page.screenshot(path=str(out/'notes-summary-tree-1920x1080.png'))
    page.locator('.organize-mode-bar').get_by_role('tab', name='核心观点').click()
    page.locator('.viewpoint-slip').first.wait_for()
    page.wait_for_timeout(420)
    page.screenshot(path=str(out/'notes-viewpoints-1920x1080.png'))

    # Clicking card body keeps user on 整理; clicking timestamp switches to 原文 and locates cue
    page.locator('.viewpoint-slip .slip-body').first.click()
    assert page.locator('#tab-notes-drafts').get_attribute('aria-selected') == 'true'
    assert page.locator('.note-read .sentence[aria-pressed="true"]').count() == 1
    page.locator('.viewpoint-slip .slip-ref-chip').first.click()
    page.wait_for_timeout(200)
    assert page.locator('#tab-notes-source').get_attribute('aria-selected') == 'true'
    page.get_by_role('button', name='← 返回整理', exact=True).click()
    assert page.locator('#tab-notes-drafts').get_attribute('aria-selected') == 'true'
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
                page.locator('#tab-notes-source').click()
                source = page.locator('.note-read')
                assert source.bounding_box()['width'] >= 220
                export = source.get_by_role('button', name='导出 Markdown', exact=True)
                export.scroll_into_view_if_needed()
                assert export.bounding_box()['y'] + export.bounding_box()['height'] <= height + 1
                page.locator('#tab-notes-drafts').click()
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
    page.wait_for_timeout(600)
    assert page.locator('.home-mode').count() == 0

    # Verify 1.0.2 fullscreen scaling: Home mailbox/paper & Settings expand proportionally at 1920x1080 vs 1440x940
    home_1440 = page.evaluate("""() => {
      const mail = document.querySelector('.letter-station.publish .desk-mailbox').getBoundingClientRect();
      const paper = document.querySelector('.letter-station.publish .writing-paper').getBoundingClientRect();
      const flapImg = document.querySelector('.letter-station.publish .slot-flap img');
      return { mailW: mail.width, paperW: paper.width, flapLoaded: Boolean(flapImg && flapImg.complete && flapImg.naturalWidth > 0) };
    }""")
    assert home_1440['flapLoaded'], ('3D mailbox flap layer failed to load', home_1440)
    page.set_viewport_size({'width': 1920, 'height': 1080})
    page.wait_for_timeout(300)
    home_1920 = page.evaluate("""() => {
      const mail = document.querySelector('.letter-station.publish .desk-mailbox').getBoundingClientRect();
      const paper = document.querySelector('.letter-station.publish .writing-paper').getBoundingClientRect();
      return { mailW: mail.width, paperW: paper.width, scrollH: document.documentElement.scrollHeight, innerH: window.innerHeight };
    }""")
    assert home_1920['mailW'] > home_1440['mailW'] * 1.15, ('Home mailbox did not scale up in fullscreen', home_1440, home_1920)
    assert home_1920['paperW'] > home_1440['paperW'] * 1.15, ('Home paper did not scale up in fullscreen', home_1440, home_1920)
    page.screenshot(path=str(out/'home-fullscreen-1920x1080.png'))
    page.get_by_role('button', name='设置', exact=True).click()
    page.wait_for_timeout(500)
    settings_1920 = page.evaluate("""() => {
      const layout = document.querySelector('.settings-layout').getBoundingClientRect();
      const body = document.querySelector('.settings-body').getBoundingClientRect();
      return { layoutW: layout.width, bodyW: body.width };
    }""")
    assert settings_1920['layoutW'] > 1550, ('Settings layout did not expand to fullscreen', settings_1920)
    page.screenshot(path=str(out/'settings-fullscreen-1920x1080.png'))
    page.locator('.settings-nav').get_by_role('button', name='Obsidian').click()
    page.wait_for_timeout(200)
    assert page.locator('.obsidian-vault-card').count() == 2
    page.screenshot(path=str(out/'settings-obsidian-dual-1920x1080.png'))
    results['fullscreen_scaling'] = {'home_1440': home_1440, 'home_1920': home_1920, 'settings_1920': settings_1920}

    # Verify 1.0.2 floating Toast: clicking 打开成片目录 causes ZERO brazier/content shift and auto-dismisses
    page.get_by_role('button', name='投稿', exact=True).click()
    page.wait_for_timeout(500)
    page.locator('[data-entry-id="'+publish_entry['id']+'"] .incoming-open').click()
    # Prepare & run the simulated publish group so shape_result yields a real local final_video_url artifact
    patch_r = page.request.patch(
        origin + '/desktop/inbox/groups/' + publish_group,
        data={'revision': 0, 'options': {}, 'overrides': {}, 'prepared': ['output', 'style', 'publish', 'translation']},
        headers={'Origin': origin},
    )
    assert patch_r.ok, patch_r.text()
    rev = patch_r.json()['revision']
    api('/desktop/inbox/groups/' + publish_group + '/start', {
        'revision': rev, 'confirmed': True, 'entry_ids': [publish_entry['id']],
    })
    for _ in range(120):
        cur = next(item for item in page.request.get(origin + '/desktop/inbox/queue').json()['entries'] if item['id'] == publish_entry['id'])
        if cur['status'] == 'succeeded' and cur.get('result', {}).get('final_video_url'):
            break
        assert cur['status'] not in {'failed', 'blocked', 'rejected'}, cur
        page.wait_for_timeout(200)
    else:
        raise AssertionError(('Publish fixture never reached succeeded with final_video_url', cur))
    page.locator('.publish .letter-state.succeeded').wait_for(state='visible', timeout=8000)
    page.locator('#tab-preview').click()
    page.wait_for_timeout(250)
    page.route('**/desktop/open-path', lambda route: route.fulfill(status=200, json={'ok': True}))
    before_toast = page.evaluate("""() => ({
      brazier: document.querySelector('.publish .publish-scene').getBoundingClientRect().toJSON(),
      content: document.querySelector('.publish .publish-content').getBoundingClientRect().toJSON(),
    })""")
    page.get_by_role('button', name='打开成片目录', exact=True).click()
    page.locator('.publish .workbench-toast').wait_for(state='visible')
    page.screenshot(path=str(out/'publish-toast-visible.png'))
    during_toast = page.evaluate("""() => ({
      brazier: document.querySelector('.publish .publish-scene').getBoundingClientRect().toJSON(),
      content: document.querySelector('.publish .publish-content').getBoundingClientRect().toJSON(),
    })""")
    assert abs(during_toast['brazier']['top'] - before_toast['brazier']['top']) < 0.5, (before_toast, during_toast)
    assert abs(during_toast['content']['top'] - before_toast['content']['top']) < 0.5, (before_toast, during_toast)
    page.locator('.publish .workbench-toast').wait_for(state='detached', timeout=5000)
    page.unroute('**/desktop/open-path')
    results['toast_zero_shift_and_auto_dismiss'] = True

    page.set_viewport_size({'width': 1440, 'height': 940})
    page.get_by_role('button', name='信箱', exact=True).click()
    page.wait_for_timeout(500)
    page.locator('.letter-station.publish input.rule-input').first.fill('https://example.com/video-'+token)
    page.evaluate("""() => {
      window.__flapAngles = [];
      let live = true;
      window.__stopFlapSample = () => { live = false; };
      function sample() {
        if (!live) return;
        const el = document.querySelector('.letter-station.publish .slot-flap');
        if (el) window.__flapAngles.push(el.style.transform || getComputedStyle(el).transform);
        requestAnimationFrame(sample);
      }
      requestAnimationFrame(sample);
    }""")
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
    page.wait_for_function("() => document.querySelector('.letter-station.publish').dataset.phase==='insert'")
    page.wait_for_timeout(320)
    page.screenshot(path=str(out/'home-mailbox-flap-open.png'))
    page.set_viewport_size({'width': 1280, 'height': 800})
    page.wait_for_function("() => document.querySelector('.letter-station.publish').dataset.phase==='idle'")
    flap_samples = page.evaluate("() => { window.__stopFlapSample?.(); return window.__flapAngles || []; }")
    assert any('rotateX(' in s for s in flap_samples), ('3D mailbox flap did not animate during delivery', flap_samples[:10])
    results['mailbox_flap_animated'] = True
    assert page.locator('.fold-sheet,.routing-letter,.cast-shadow').count() == 0
    assert page.locator('.letter-station.publish').get_attribute('data-phase') == 'idle'

    # v1.0.4 Regression: verify ZERO scroll overflow, ZERO sibling jitter, and envelope strictly in-viewport across viewports
    delivery_bounds = []
    for vw, vh in [(1440, 940), (1280, 800), (1280, 720), (1920, 1080), (950, 680)]:
        page.set_viewport_size({'width': vw, 'height': vh})
        page.wait_for_timeout(250)
        page.locator('.letter-station.publish input.rule-input').first.fill(f'https://example.com/video-bounds-{vw}x{vh}-{token}')
        page.evaluate("""() => {
          const sib = document.querySelector('.letter-station.notes').getBoundingClientRect();
          window.__boundsStats = {
            baseTop: sib.top, baseLeft: sib.left,
            maxDriftTop: 0, maxDriftLeft: 0,
            maxScrollY: 0, maxScrollX: 0,
            minEnvVisTop: 99999, maxEnvVisBottom: -99999, frames: 0,
          };
          let live = true;
          window.__stopBounds = () => { live = false; };
          function sample() {
            if (!live) return;
            const home = document.querySelector('.home-view');
            const s = document.querySelector('.letter-station.notes').getBoundingClientRect();
            const env = document.querySelector('.letter-station.publish .delivery-envelope:not(.delivery-placeholder)');
            const st = window.__boundsStats;
            st.frames++;
            st.maxDriftTop = Math.max(st.maxDriftTop, Math.abs(s.top - st.baseTop));
            st.maxDriftLeft = Math.max(st.maxDriftLeft, Math.abs(s.left - st.baseLeft));
            st.maxScrollY = Math.max(st.maxScrollY, home.scrollHeight - home.clientHeight);
            st.maxScrollX = Math.max(st.maxScrollX, home.scrollWidth - home.clientWidth);
            if (env && !env.closest('.slot-window')) {
              const r = env.getBoundingClientRect();
              if (r.height > 2) {
                const visTop = r.top + r.height * 0.3877;
                const visBot = r.top + r.height * 0.85156;
                st.minEnvVisTop = Math.min(st.minEnvVisTop, visTop);
                st.maxEnvVisBottom = Math.max(st.maxEnvVisBottom, visBot);
              }
            }
            requestAnimationFrame(sample);
          }
          requestAnimationFrame(sample);
        }""")
        page.get_by_role('button', name='投递投稿信件', exact=True).click()
        page.wait_for_function("() => document.querySelector('.letter-station.publish').dataset.phase==='fold'")
        page.wait_for_function("() => document.querySelector('.letter-station.publish').dataset.phase==='idle'", timeout=10000)
        stats = page.evaluate("() => { window.__stopBounds?.(); return window.__boundsStats; }")
        assert stats['maxScrollY'] <= 1, (vw, vh, stats)
        assert stats['maxScrollX'] <= 1, (vw, vh, stats)
        assert stats['maxDriftTop'] <= 0.5 and stats['maxDriftLeft'] <= 0.5, ('Sibling jitter detected', vw, vh, stats)
        assert stats['minEnvVisTop'] >= -2 and stats['maxEnvVisBottom'] <= vh + 2, ('Envelope overflowed viewport', vw, vh, stats)
        delivery_bounds.append({'viewport': [vw, vh], **stats})
    results['delivery_zero_jitter_and_bounds'] = delivery_bounds
    page.set_viewport_size({'width': 1280, 'height': 800})
    page.emulate_media(reduced_motion='reduce')
    page.get_by_role('button', name='设置', exact=True).click()
    page.wait_for_timeout(100)
    assert page.locator('.is-deck-in,.is-deck-out').count() == 0
    # Verify global Ctrl+1..4 navigation shortcuts
    page.keyboard.press('Control+2')
    page.wait_for_timeout(80)
    assert page.locator('main#workspace').get_attribute('data-view') == 'publish'
    page.keyboard.press('Control+3')
    page.wait_for_timeout(80)
    assert page.locator('main#workspace').get_attribute('data-view') == 'notes'
    page.keyboard.press('Control+4')
    page.wait_for_timeout(80)
    assert page.locator('main#workspace').get_attribute('data-view') == 'settings'
    assert not results['errors'], results['errors']
    browser.close()

(out/'ui-results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
print(f"PASS: three mode payloads, keyboard, edits, {len(results['matrix'])} layouts, focus, resize cleanup, reduced motion")
