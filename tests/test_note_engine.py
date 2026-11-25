import json
from types import SimpleNamespace

import httpx
import pytest

from app import knowledge as k, note_engine as e, main as media


@pytest.fixture
def source(tmp_path, monkeypatch):
    monkeypatch.setattr(media, 'DATA_DIR', tmp_path)
    k.initialize()
    # 6000 Chinese chars (~6300 calibrated tokens) -> multi-leaf across all 3 modes.
    return k.register(
        None,
        source_kind='local',
        source='fixture',
        title='fixture',
        media_type='note',
        note_body='中文观点。' * 1200,
    )


def model(monkeypatch, fail_at=None, overflow=False):
    calls = []

    def ask(self, operation, instruction, payload):
        calls.append(operation)
        if fail_at and len(calls) == fail_at:
            raise RuntimeError('interrupted')
        if operation == 'read':
            text = payload[0]['text']
            idx = len(calls)
            kinds = ['judgment', 'fact', 'story', 'method', 'statement']
            return {
                'topic': f'章节{idx}',
                'capsule': f'中文概述{idx}',
                'key_points': [f'要点{idx}'],
                'overflow': overflow and len(text) > 100,
                'cards': [
                    {
                        'kind': kinds[idx % len(kinds)],
                        'claim': f'独立核心主张编号{idx}关于系统设计方法',
                        'topic': f'主题{idx}',
                        'importance': 3,
                        'specificity': 3,
                        'refs': [payload[0]['id']],
                        'evidence': f'论据{idx}',
                        'example': f'例子{idx}',
                    }
                ],
            }
        if operation == 'merge':
            assert 2 <= len(payload) <= 4
            assert all(e.tokens(p['capsule']) <= 512 for p in payload)
            return {'title': '合并章节', 'topic': '总主题', 'capsule': '总概述', 'highlights': ['主线要点']}
        if operation == 'merge_candidates':
            cands = payload['candidates']
            assert len(cands) >= 2
            return {
                'capsule': '归约概述',
                'keep': [
                    {'primary': c['id'], 'merged_from': [], 'topic': c['topic'], 'claim': c['claim'], 'evidence': c['evidence']}
                    for c in cands[:payload['max_keep']]
                ],
            }
        if operation == 'dedup':
            assert len(payload) <= 8
            return {'duplicates': []}
        if operation == 'render':
            chapters = payload.get('chapters') or []
            return {
                'cards': [
                    {'topic': '甲', 'claim': '摘要甲', 'evidence': '依据甲', 'chapter_ids': [0] if chapters else []},
                    {'topic': '乙', 'claim': '摘要乙', 'evidence': '依据乙', 'chapter_ids': [min(1, len(chapters) - 1)] if chapters else []},
                    {'topic': '丙', 'claim': '摘要丙', 'evidence': '依据丙', 'chapter_ids': [len(chapters) - 1] if chapters else []},
                ]
            }
        if operation in {'translate', 'translate_cited'}:
            return {'items': [{'id': item['id'], 'text': '中文译文:' + item['text'][:40]} for item in payload]}
        raise AssertionError(operation)

    monkeypatch.setattr(e.Engine, 'ask', ask)
    return calls


@pytest.mark.parametrize('mode', ['summary', 'curated', 'comprehensive'])
def test_bounded_tree_and_idempotence(source, monkeypatch, mode):
    calls = model(monkeypatch)
    count = e.generate(source, 'test', 'test', mode)
    assert count > 0
    completed = len(calls)
    assert e.generate(source, 'test', 'test', mode) == 0
    assert len(calls) == completed
    state = e.status(source)
    assert state['status'] == 'succeeded'
    assert state['completed_blocks'] == state['total_blocks']
    with k.database() as db:
        leaves = list(
            db.execute(
                "SELECT lo,hi FROM note_node WHERE run=? AND cue IS NOT NULL AND status='done' ORDER BY lo",
                (state['id'],),
            )
        )
    assert leaves[0]['lo'] == 0 and leaves[-1]['hi'] == 6000
    assert all(a['hi'] == b['lo'] for a, b in zip(leaves, leaves[1:]))
    # Curated never performs O(N) compare; summary cards carry non-empty chapter refs.
    assert 'compare' not in calls
    if mode == 'summary':
        from app.note_pages import summary_tree
        tree = summary_tree(source)
        assert tree is not None and len(tree['nodes']) >= 2
        assert tree['overview'] is not None
        assert any(node['viewpoints'] or node['children'] for node in tree['nodes'])


def test_restart_keeps_completed_nodes_and_edits(source, monkeypatch):
    model(monkeypatch, fail_at=2)
    with pytest.raises(RuntimeError):
        e.generate(source, 'test', 'test', 'comprehensive')
    assert e.status(source)['completed_blocks'] >= 1
    model(monkeypatch)
    assert e.generate(source, 'test', 'test', 'comprehensive') > 0
    card = k.read_transcript(source)['cards'][0]
    k.update_card(source, card['id'], k.CardText(claim='手改'))
    model(monkeypatch)
    e.generate(source, 'test', 'test', 'summary')
    assert any(c['claim'] == '手改' for c in k.read_transcript(source)['cards'])


def test_overflow_strictly_splits_and_keeps_all_candidates(tmp_path, monkeypatch):
    monkeypatch.setattr(media, 'DATA_DIR', tmp_path)
    k.initialize()
    ident = k.register(None, source_kind='local', source='overflow-src', title='ov', media_type='note', note_body='中文观点。' * 400)
    model(monkeypatch, overflow=True)
    count = e.generate(ident, 'test', 'test', 'comprehensive')
    assert count > 20
    state = e.status(ident)
    assert state['completed_blocks'] >= count
    with k.database() as db:
        assert db.execute('SELECT count(*) FROM note_candidate WHERE run=?', (state['id'],)).fetchone()[0] == count


def test_pages_are_bounded_and_summary_has_chapter_refs(source, monkeypatch, tmp_path):
    from app.note_pages import page, markdown_to, node_references, candidate_references
    model(monkeypatch)
    e.generate(source, 'test', 'test', 'summary')
    doc = page(source, view_mode='summary')
    tree = doc['summary_tree']
    assert tree is not None
    assert tree['overview'] is not None
    assert len(tree['nodes']) >= 2
    first_node = tree['nodes'][0]
    refs = node_references(source, first_node['id'])
    assert len(refs['items']) >= 1
    first_leaf = first_node if not first_node['children'] else first_node['children'][0]
    assert len(first_leaf['viewpoints']) >= 1
    vp_refs = candidate_references(source, first_leaf['viewpoints'][0]['id'])
    assert len(vp_refs['items']) >= 1
    markdown_to(source, tmp_path / 'out.md', view_mode='summary')
    md = (tmp_path / 'out.md').read_text(encoding='utf-8')
    assert '全篇总览' in md and first_node['title'] in md and first_leaf['viewpoints'][0]['claim'] in md


def test_request_budget_rejects_before_network(source, monkeypatch):
    e.initialize()
    engine = e.Engine(source, 'key', 'mock', 'comprehensive', None)
    engine.seed()

    def never(*a, **kw):
        raise AssertionError('oversized request reached network')

    monkeypatch.setattr(httpx.Client, 'post', never)
    with pytest.raises(e.TooLarge):
        engine.ask('read', 'JSON', {'text': '字' * 10000})


def test_mode_round_trip_preserves_ids_and_edits(source, monkeypatch):
    model(monkeypatch)
    e.generate(source, 'key', 'mock', 'comprehensive')
    original = k.read_transcript(source)['cards']
    k.update_card(source, original[0]['id'], k.CardText(claim='手改保留'))
    e.generate(source, 'key', 'mock', 'summary')
    monkeypatch.setattr(e.Engine, 'ask', lambda *a: pytest.fail('completed run called the model'))
    e.generate(source, 'key', 'mock', 'comprehensive')
    restored = k.read_transcript(source)['cards']
    assert [c['id'] for c in restored] == [c['id'] for c in original]
    assert restored[0]['claim'] == '手改保留'


def test_missing_source_range_cannot_be_published(source, monkeypatch):
    model(monkeypatch)
    e.initialize()
    engine = e.Engine(source, 'key', 'mock', 'comprehensive', None)
    engine.seed()
    with k.database() as db:
        rows = [dict(r) for r in db.execute('SELECT * FROM note_node WHERE run=?', (engine.run,))]
    for row in rows:
        engine.leaf(row)
    with k.database() as db:
        db.execute('UPDATE note_span SET lo=lo+1 WHERE node=? AND local=1', (rows[0]['id'],))
    with pytest.raises(ValueError, match='覆盖'):
        engine.validate_coverage()


def test_minimal_truncation_stops_and_preserves_old_cards(tmp_path, monkeypatch):
    monkeypatch.setattr(media, 'DATA_DIR', tmp_path)
    k.initialize()
    ident = k.register(None, source_kind='local', source='minimum', title='one', media_type='note', note_body='字')
    with k.database() as db:
        db.execute("INSERT INTO card(transcript_id,claim,evidence,example,refs,origin_key) VALUES(?,'旧稿','','','[1]','legacy')", (ident,))
    calls = []

    def truncate(*args):
        calls.append(1)
        raise e.TooLarge('输出截断')

    monkeypatch.setattr(e.Engine, 'ask', truncate)
    with pytest.raises(ValueError, match='最小片段'):
        e.generate(ident, 'key', 'mock', 'comprehensive')
    assert len(calls) == 1
    assert k.read_transcript(ident)['cards'][0]['claim'] == '旧稿'
    assert e.status(ident)['status'] == 'failed'


def test_small_context_uses_binary_tree(source, monkeypatch):
    monkeypatch.setenv('MEDIA_NOTES_CONTEXT', '6144')
    base = model(monkeypatch)
    original = e.Engine.ask

    def bounded(self, operation, instruction, payload):
        if operation == 'merge':
            assert len(payload) == 2
        return original(self, operation, instruction, payload)

    monkeypatch.setattr(e.Engine, 'ask', bounded)
    e.generate(source, 'key', 'mock', 'summary')
    assert 'merge' in base


def test_calibrated_token_chunking_packs_2000_chars_into_one_leaf(tmp_path, monkeypatch):
    monkeypatch.setattr(media, 'DATA_DIR', tmp_path)
    k.initialize()
    ident = k.register(None, source_kind='local', source='compact-zh', title='compact', media_type='note', note_body='中文观点。' * 400)
    calls = model(monkeypatch)
    e.generate(ident, 'key', 'mock', 'summary')
    assert calls.count('read') == 1
    assert calls.count('merge') == 0


def test_language_routing_matrix_zh_mixed_foreign(tmp_path, monkeypatch):
    monkeypatch.setattr(media, 'DATA_DIR', tmp_path)
    k.initialize()

    # 1. Chinese with English product names -> zh_native (0 translation calls in all modes).
    zh_id = k.register(
        None, source_kind='local', source='zh-tech', title='zh-tech', media_type='note',
        note_body='今天聊聊 DeepSeek V3 和 NVIDIA CUDA 在本地部署 Whisper 模型时的显存优化方案。\n' * 10,
    )
    assert e.detect_document_language(zh_id)['lang_class'] == 'zh_native'
    calls = model(monkeypatch)
    e.generate(zh_id, 'k', 'm1', 'comprehensive')
    assert 'translate' not in calls and 'translate_cited' not in calls

    # 2. Foreign transcript -> summary: 0 translation; curated: cited_only; comprehensive: full_cached.
    en_lines = '\n'.join(f'Sentence {i}: distributed consensus requires explicit quorum intersection under network partitions.' for i in range(1, 15))
    en_id = k.register(None, source_kind='local', source='en-doc', title='en', media_type='note', note_body=en_lines)
    assert e.detect_document_language(en_id)['lang_class'] == 'foreign'

    calls_sum = model(monkeypatch)
    e.generate(en_id, 'k', 'm-sum', 'summary')
    assert 'translate' not in calls_sum and 'translate_cited' not in calls_sum

    calls_cur = model(monkeypatch)
    e.generate(en_id, 'k', 'm-cur', 'curated')
    assert 'translate' not in calls_cur
    assert 'translate_cited' in calls_cur
    cur_cards = k.read_transcript(en_id)['cards']
    assert cur_cards and cur_cards[0]['quote_translation'].startswith('中文译文:')

    calls_comp = model(monkeypatch)
    e.generate(en_id, 'k', 'm-comp', 'comprehensive')
    assert 'translate' in calls_comp

    # 3. Mixed transcript in comprehensive mode -> translates ONLY foreign spans, not Chinese spans.
    mixed_body = '\n'.join([
        '第一段纯中文说明核心架构原则和设计边界。',
        'Second paragraph in English explains why backpressure prevents cascading queue failures.',
        '第三段继续用中文解释实验指标和工程折中。',
        'Fourth paragraph in English details the memory allocator tradeoffs for long streams.',
    ])
    mix_id = k.register(None, source_kind='local', source='mixed-doc', title='mix', media_type='note', note_body=mixed_body)
    assert e.detect_document_language(mix_id)['lang_class'] == 'mixed'
    translated_inputs = []
    base_ask = e.Engine.ask

    def spy_ask(self, operation, instruction, payload):
        if operation == 'translate':
            translated_inputs.extend(item['text'] for item in payload)
        return base_ask(self, operation, instruction, payload)

    model(monkeypatch)
    base_ask = e.Engine.ask
    monkeypatch.setattr(e.Engine, 'ask', spy_ask)
    e.generate(mix_id, 'k', 'm-mix', 'comprehensive')
    assert len(translated_inputs) == 2
    assert all('English' in text for text in translated_inputs)


def test_curated_tree_reduce_merges_cross_topic_duplicates_and_unions_refs(tmp_path, monkeypatch):
    monkeypatch.setattr(media, 'DATA_DIR', tmp_path)
    k.initialize()
    body = '\n'.join(f'第{i}段讨论缓存局部性与批处理吞吐量的具体权衡。' * 12 for i in range(1, 25))
    ident = k.register(None, source_kind='local', source='curated-dedup', title='cd', media_type='note', note_body=body)

    ops = []
    leaf_idx = 0

    def ask(self, operation, instruction, payload):
        nonlocal leaf_idx
        ops.append(operation)
        if operation == 'read':
            leaf_idx += 1
            return {
                'topic': f'不同主题{leaf_idx}',
                'capsule': f'节概述{leaf_idx}',
                'overflow': False,
                'cards': [{
                    'claim': '批量合并请求能显著降低显存碎片与通信开销',
                    'topic': f'不同主题{leaf_idx}',
                    'importance': 3,
                    'specificity': 3,
                    'evidence': f'来自第{leaf_idx}节的数据',
                    'example': '',
                    'refs': [payload[0]['id']],
                }],
            }
        if operation == 'merge_candidates':
            cands = payload['candidates']
            primary = cands[0]['id']
            dups = [c['id'] for c in cands[1:]]
            return {
                'capsule': '合并总概述',
                'keep': [{
                    'primary': primary,
                    'merged_from': dups,
                    'topic': '批处理优化',
                    'claim': '批量合并请求能显著降低显存碎片与通信开销（已融合）',
                    'evidence': '融合多节实验数据',
                }],
            }
        raise AssertionError(operation)

    monkeypatch.setattr(e.Engine, 'ask', ask)
    count = e.generate(ident, 'k', 'm', 'curated')
    assert count == 1
    assert 'merge_candidates' in ops
    assert 'compare' not in ops
    card = k.read_transcript(ident)['cards'][0]
    assert '已融合' in card['claim']
    assert len(card['refs']) >= 2


def test_comprehensive_local_bucketing_skips_llm_for_distinct_and_merges_similar(tmp_path, monkeypatch):
    monkeypatch.setattr(media, 'DATA_DIR', tmp_path)
    k.initialize()
    body = '\n'.join(f'段落{i}独立内容。' * 40 for i in range(1, 20))
    ident = k.register(None, source_kind='local', source='comp-bucket', title='cb', media_type='note', note_body=body)

    dedup_calls = []
    read_num = 0
    claims = [
        '使用外部存储归约可以避免上下文溢出报错',
        '使用外部存储归约能够避免上下文溢出报错',  # Near duplicate -> bucketed together!
        '显卡队列采用双线轮询可彻底杜绝显存不足',
        '抖音链接应优先读取视频毫秒时长而非背景音乐时长',
        '前端碎纸纹理应当在渲染外缓存以保持稳定帧率',
        '音频预解码放到显卡队列之外能减少空闲显存占用',
        '中英混排技术访谈无需翻译包含英文术语的中文句',
        '投稿火盆的木柴落点应与前檐遮挡层精确对齐',
        '摘要模式卡片需要保留对应章节的起始字幕编号',
    ]

    def ask(self, operation, instruction, payload):
        nonlocal read_num
        if operation == 'read':
            idx = read_num
            read_num += 1
            claim = claims[idx] if idx < len(claims) else f'第{idx}号专题关于完全独立的工程实践{chr(0x4e00 + idx * 17)}'
            return {
                'topic': '架构' if idx < 2 else f'领域{idx}',
                'capsule': f'概述{idx}',
                'overflow': False,
                'cards': [{
                    'claim': claim, 'topic': '架构' if idx < 2 else f'领域{idx}',
                    'importance': 3, 'specificity': 3, 'evidence': '', 'example': '', 'refs': [payload[0]['id']],
                }],
            }
        if operation == 'merge':
            return {'topic': '总览', 'capsule': '合并概述'}
        if operation == 'dedup':
            dedup_calls.append(payload)
            return {'duplicates': [{'dup': 2, 'of': 1}]}
        raise AssertionError(operation)

    monkeypatch.setattr(e.Engine, 'ask', ask)
    count = e.generate(ident, 'k', 'm', 'comprehensive')
    assert len(dedup_calls) == 1
    assert len(dedup_calls[0]) == 2
    assert count == read_num - 1


def test_cross_mode_reuse_skips_leaf_reads_when_switching_from_comprehensive(source, monkeypatch):
    from app.note_pages import summary_tree
    calls1 = model(monkeypatch)
    e.generate(source, 'k', 'shared-model', 'comprehensive')
    assert calls1.count('read') >= 2
    # Parallel co-generation already populated summary tree & curated viewpoints!
    modes = e.modes_status(source, model='shared-model')
    assert modes['comprehensive']['available']
    assert modes['curated']['available']
    assert modes['summary']['available']
    assert summary_tree(source) is not None

    # Switching to summary or curated hits already-derived runs with 0 LLM calls.
    calls2 = model(monkeypatch)
    assert e.generate(source, 'k', 'shared-model', 'summary') >= 1
    assert calls2 == []

    calls3 = model(monkeypatch)
    assert e.generate(source, 'k', 'shared-model', 'curated') >= 1
    assert calls3 == []


def test_summary_stays_lightweight_and_curated_reuses_summary_leaves_zero_read(source, monkeypatch):
    calls_sum = model(monkeypatch)
    e.generate(source, 'k', 'reuse-from-sum', 'summary')
    assert calls_sum.count('read') >= 2
    assert 'merge_candidates' not in calls_sum
    modes_after_sum = e.modes_status(source, model='reuse-from-sum')
    assert modes_after_sum['summary']['available'] is True
    assert modes_after_sum['curated']['available'] is False
    assert modes_after_sum['curated']['can_reuse_leaves'] is True

    # Switching to curated reuses 100% of summary's leaves & viewpoints -> 0 leaf reads!
    calls_cur = model(monkeypatch)
    assert e.generate(source, 'k', 'reuse-from-sum', 'curated', derive_siblings=False) >= 1
    assert calls_cur.count('read') == 0
    assert 'merge_candidates' in calls_cur


def test_summary_cost_model_scales_layers_and_top_count_dynamically():
    # 1. Tiny clip -> 1 layer, 1 node, no redundant root overview
    p_tiny = e.plan_summary_tree(leaf_count=1, viewpoint_count=4, total_tokens=1200)
    assert p_tiny['summary_layers'] == 1 and p_tiny['top_count'] == 1 and not p_tiny['need_root_overview']

    # 2. 25-min video (~5 leaves) -> 1 summary layer of 5 + root overview
    p_med = e.plan_summary_tree(leaf_count=5, viewpoint_count=20, total_tokens=9000)
    assert p_med['summary_layers'] == 1 and p_med['top_count'] == 5 and p_med['need_root_overview']

    # 3. 1-hr talk (~10 leaves) -> automatically promotes to 2 summary layers!
    p_hr = e.plan_summary_tree(leaf_count=10, viewpoint_count=40, total_tokens=22000)
    assert p_hr['summary_layers'] == 2 and 3 <= p_hr['top_count'] <= 6

    # 4. 2-hr podcast (~16 leaves) -> 2 summary layers with comfortable top scan width
    p_pod = e.plan_summary_tree(leaf_count=16, viewpoint_count=64, total_tokens=40000)
    assert p_pod['summary_layers'] == 2 and 4 <= p_pod['top_count'] <= 7

    # 5. Book-scale (~54 leaves) -> 3 summary layers!
    p_book = e.plan_summary_tree(leaf_count=54, viewpoint_count=210, total_tokens=160000)
    assert p_book['summary_layers'] == 3 and 4 <= p_book['top_count'] <= 8

    # 6. Small context constraint strictly enforces branching <= 2
    p_small = e.plan_summary_tree(leaf_count=12, viewpoint_count=48, total_tokens=25000, input_budget=3072)
    assert p_small['branching_factor'] <= 2

    # 7. Balanced partitioning produces no lonely 1-item tail
    groups = e.balanced_groups(list(range(14)), 5)
    assert [len(g) for g in groups] == [3, 3, 3, 3, 2]


def test_summary_tree_multi_layer_editing_and_viewpoint_kinds(tmp_path, monkeypatch):
    from app.note_pages import page, summary_tree
    monkeypatch.setattr(media, 'DATA_DIR', tmp_path)
    k.initialize()
    # ~24,000 Chinese chars -> ~10+ leaves -> guarantees multi-layer (summary_layers >= 2) tree!
    body = '\n'.join(f'第{i}节探讨系统边界、真实案例与反直觉历史典故。' * 12 for i in range(1, 90))
    ident = k.register(None, source_kind='local', source='multi-layer', title='深度长谈', media_type='note', note_body=body)
    model(monkeypatch)
    e.generate(ident, 'k', 'm-deep', 'summary')
    tree = summary_tree(ident)
    assert tree is not None
    assert tree['plan']['summary_layers'] >= 2
    assert tree['overview'] is not None
    assert any(node['children'] for node in tree['nodes'])
    # Verify concrete viewpoints sit at leaf level with normalized kinds
    leaf_vps = []
    def collect(nodes):
        for n in nodes:
            leaf_vps.extend(n['viewpoints'])
            collect(n['children'])
    collect(tree['nodes'])
    assert len(leaf_vps) >= 8
    assert {'judgment', 'fact', 'story', 'method', 'statement'}.issubset({vp['kind'] for vp in leaf_vps})

    # Edit a summary tree node and verify persistence
    target_node = tree['nodes'][0]
    e.update_tree_node(ident, target_node['id'], '修订主题标题', '修订后的多层压缩摘要。')
    reloaded = page(ident, view_mode='summary')['summary_tree']
    assert reloaded['nodes'][0]['title'] == '修订主题标题'
    assert reloaded['nodes'][0]['summary'] == '修订后的多层压缩摘要。'
    assert reloaded['nodes'][0]['edited'] is True


def test_http_400_context_overflow_triggers_binary_split(tmp_path, monkeypatch):
    monkeypatch.setattr(media, 'DATA_DIR', tmp_path)
    k.initialize()
    ident = k.register(None, source_kind='local', source='http400', title='h400', media_type='note', note_body='测试句子。' * 120)

    real_client = httpx.Client
    seen_lengths = []

    def fake_transport(request):
        body = json.loads(request.content)
        payload = json.loads(body['messages'][1]['content'])
        if '合并相邻概述' in body['messages'][0]['content']:
            return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps({'capsule': '总述'})}}]})
        text_len = sum(len(item['text']) for item in payload)
        seen_lengths.append(text_len)
        if text_len > 350:
            return httpx.Response(400, json={'error': {'message': "This model's maximum context length is 4096 tokens"}})
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps({
            'capsule': '分段概述', 'overflow': False,
            'cards': [{'claim': f'结论{len(seen_lengths)}', 'topic': '主题', 'importance': 3, 'specificity': 3, 'refs': [payload[0]['id']]}],
        })}}]})

    monkeypatch.setattr(e, 'httpx', SimpleNamespace(
        Client=lambda **kw: real_client(transport=httpx.MockTransport(fake_transport), **kw),
        TimeoutException=httpx.TimeoutException,
        NetworkError=httpx.NetworkError,
    ))
    count = e.generate(ident, 'k', 'm', 'comprehensive')
    assert count >= 2
    assert any(length > 350 for length in seen_lengths)
    assert any(length <= 350 for length in seen_lengths)


def test_on_demand_translate_page_and_model_dedup(tmp_path, monkeypatch):
    from app.note_pages import page
    monkeypatch.setattr(media, 'DATA_DIR', tmp_path)
    k.initialize()
    ident = k.register(
        None, source_kind='local', source='page-trans', title='pt', media_type='note',
        note_body='This is an English paragraph for testing on-demand page translation.\n这是中文段落无需翻译。',
    )
    calls = model(monkeypatch)
    translated = e.translate_page(ident, 'k', 'model-a', cue_after=0, limit=32)
    assert translated == 1
    assert calls == ['translate']

    # Second call for same model hits cache -> 0 new translations.
    assert e.translate_page(ident, 'k', 'model-a', cue_after=0, limit=32) == 0

    # Translating again with a second model doesn't concatenate duplicate translations in page().
    assert e.translate_page(ident, 'k', 'model-b', cue_after=0, limit=32) == 1
    doc = page(ident)
    assert doc['cues'][0]['translation'].count('中文译文:') == 1
    assert doc['cues'][1]['translation'] == ''


def test_douyin_duration_units_are_explicit():
    from app.sites.resolve import player_feature
    for duration in (500, 999, 1000, 275000, 1923067):
        payload = {'aweme_id': '7123456789012345678', 'video': {'duration': duration, 'playAddr': [{'src': 'https://example.com/video.mp4'}]}}
        assert player_feature(json.dumps(payload), '7123456789012345678')['duration'] == duration / 1000
