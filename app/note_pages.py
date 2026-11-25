"""Bounded pages, multi-level summary tree projections and streaming exports for the knowledge workspace."""
import json
from typing import Any

from app import knowledge as k
from app import note_engine as engine


def _preferred_translation_model(db, transcript_id):
    row = db.execute(
        '''SELECT r.model FROM note_active a JOIN note_run r ON a.run=r.id
           WHERE a.transcript_id=? AND r.model!='' LIMIT 1''',
        (transcript_id,),
    ).fetchone()
    if row and row[0]:
        return row[0]
    row = db.execute(
        'SELECT model FROM note_translation_part WHERE transcript=? ORDER BY rowid DESC LIMIT 1',
        (transcript_id,),
    ).fetchone()
    return row[0] if row else None


def _active_mode(db, transcript_id) -> str:
    row = db.execute(
        'SELECT r.mode FROM note_active a JOIN note_run r ON a.run=r.id WHERE a.transcript_id=? LIMIT 1',
        (transcript_id,),
    ).fetchone()
    return row[0] if row and row[0] in {'summary', 'curated', 'comprehensive'} else ''


def _cue_times(db, transcript_id, cue_numbers: set[int]) -> dict[int, tuple[int, int]]:
    nums = sorted(n for n in cue_numbers if isinstance(n, int) and n > 0)
    if not nums:
        return {}
    result: dict[int, tuple[int, int]] = {}
    for start in range(0, len(nums), 400):
        chunk = nums[start:start + 400]
        rows = db.execute(
            'SELECT number, start_ms, end_ms FROM cue WHERE transcript_id=? AND number IN ('
            + ','.join('?' for _ in chunk)
            + ')',
            [transcript_id, *chunk],
        ).fetchall()
        for r in rows:
            result[r['number']] = (r['start_ms'], r['end_ms'])
    return result


def _candidate_quote_translation(db, transcript_id: int, model: str | None, candidate_id: int) -> str:
    if not model:
        return ''
    rows = db.execute(
        '''SELECT DISTINCT s.cue, s.lo, json_extract(t.text, '$[' || (p.local-1) || '].text') AS translated
           FROM (
             SELECT ? AS candidate UNION SELECT candidate FROM note_relation WHERE duplicate_of=?
           ) ch
           JOIN note_candidate_span cs ON cs.candidate=ch.candidate
           JOIN note_span s ON cs.node=s.node AND cs.local=s.local
           JOIN note_translation_part p
             ON p.transcript=? AND p.model=? AND p.cue=s.cue AND p.lo=s.lo AND p.hi=s.hi
           JOIN note_translation t ON p.key=t.key
           ORDER BY s.cue, s.lo LIMIT 6''',
        (candidate_id, candidate_id, transcript_id, model),
    ).fetchall()
    parts = [str(r['translated'] or '').strip() for r in rows if str(r['translated'] or '').strip()]
    return ' '.join(parts)[:1200]


def summary_tree(transcript_id: int, run_id: str | None = None) -> dict[str, Any] | None:
    """Build the nested multi-level summary tree JSON (overview -> L1..LD -> leaf viewpoints)."""
    engine.initialize()
    with k.database() as db:
        if run_id:
            run_row = db.execute(
                "SELECT id, root, plan_json, model, status FROM note_run WHERE id=? AND transcript_id=? AND mode='summary'",
                (run_id, transcript_id),
            ).fetchone()
        else:
            run_row = db.execute(
                '''SELECT r.id, r.root, r.plan_json, r.model, r.status
                   FROM note_active_mode am JOIN note_run r ON am.run=r.id
                   WHERE am.transcript_id=? AND am.mode='summary' AND r.status='succeeded' LIMIT 1''',
                (transcript_id,),
            ).fetchone()
            if run_row is None:
                run_row = db.execute(
                    '''SELECT id, root, plan_json, model, status FROM note_run
                       WHERE transcript_id=? AND mode='summary' AND status='succeeded'
                       ORDER BY updated DESC LIMIT 1''',
                    (transcript_id,),
                ).fetchone()
        if not run_row or not run_row['root']:
            return None
        rid = run_row['id']
        root_id = run_row['root']
        try:
            plan = json.loads(run_row['plan_json']) if run_row['plan_json'] else {}
        except ValueError:
            plan = {}

        node_rows = db.execute(
            "SELECT * FROM note_node WHERE run=? AND status='done' ORDER BY level, position, coalesce(lo,0), id",
            (rid,),
        ).fetchall()
        if not node_rows:
            return None
        nodes_by_id = {r['id']: dict(r) for r in node_rows}
        if root_id not in nodes_by_id:
            return None

        edges = db.execute(
            '''SELECT e.parent, e.child FROM note_edge e
               JOIN note_node n ON e.child=n.id
               WHERE n.run=? AND n.status='done'
               ORDER BY n.position, coalesce(n.lo,0), n.id''',
            (rid,),
        ).fetchall()
        children_map: dict[int, list[int]] = {}
        for edge in edges:
            children_map.setdefault(edge['parent'], []).append(edge['child'])

        cand_rows = db.execute(
            '''SELECT c.* FROM note_candidate c
               LEFT JOIN note_relation r ON c.id=r.candidate
               WHERE c.run=? AND r.duplicate_of IS NULL
               ORDER BY c.node, c.id''',
            (rid,),
        ).fetchall()
        cand_ids = [c['id'] for c in cand_rows]
        cand_refs_map: dict[int, list[int]] = {}
        if cand_ids:
            for start in range(0, len(cand_ids), 400):
                chunk = cand_ids[start:start + 400]
                ref_rows = db.execute(
                    '''SELECT DISTINCT cs.candidate, s.cue
                       FROM note_candidate_span cs
                       JOIN note_span s ON cs.node=s.node AND cs.local=s.local
                       WHERE cs.candidate IN (''' + ','.join('?' for _ in chunk) + ''')
                       ORDER BY cs.candidate, s.cue''',
                    chunk,
                ).fetchall()
                for rr in ref_rows:
                    bucket = cand_refs_map.setdefault(rr['candidate'], [])
                    if len(bucket) < 12:
                        bucket.append(rr['cue'])

        trans_model = run_row['model'] or _preferred_translation_model(db, transcript_id)
        viewpoints_by_node: dict[int, list[dict[str, Any]]] = {}
        for c in cand_rows:
            viewpoints_by_node.setdefault(c['node'], []).append({
                'id': c['id'],
                'kind': engine.normalize_kind(c['kind']),
                'topic': c['topic'] or '',
                'claim': c['merged_claim'] or c['claim'] or '',
                'evidence': c['merged_evidence'] or c['evidence'] or '',
                'example': c['merged_example'] or c['example'] or '',
                'quote_translation': _candidate_quote_translation(db, transcript_id, trans_model, c['id']),
                'importance': int(c['importance'] or 0),
                'specificity': int(c['specificity'] or 0),
                'refs': cand_refs_map.get(c['id'], []),
            })

        cue_nums: set[int] = set()
        for n in nodes_by_id.values():
            if n.get('start_cue'):
                cue_nums.add(int(n['start_cue']))
            if n.get('end_cue'):
                cue_nums.add(int(n['end_cue']))
        times = _cue_times(db, transcript_id, cue_nums)

    def serialize(nid: int, depth: int, *, include_children: bool = True) -> dict[str, Any]:
        node = nodes_by_id[nid]
        state = json.loads(node['state_json']) if node.get('state_json') else {}
        raw_cap = node.get('capsule')
        try:
            summary_text = json.loads(raw_cap) if raw_cap else ''
        except ValueError:
            summary_text = str(raw_cap or '')
        title = (node.get('title') or state.get('title') or state.get('topic') or '').strip()
        highlights = list(state.get('highlights') or state.get('key_points') or [])
        start_cue = node.get('start_cue') or state.get('start_cue')
        end_cue = node.get('end_cue') or state.get('end_cue')
        start_ms = times[start_cue][0] if start_cue in times else None
        end_ms = times[end_cue][1] if end_cue in times else None
        child_ids = [cid for cid in children_map.get(nid, []) if cid in nodes_by_id]
        role = state.get('role') or ('leaf' if node['level'] == 0 else 'branch')
        return {
            'id': nid,
            'level': int(node['level']),
            'depth': depth,
            'role': role,
            'title': title or (summary_text[:22] if summary_text else f'第 {depth} 层摘要'),
            'summary': summary_text,
            'highlights': highlights,
            'start_cue': start_cue,
            'end_cue': end_cue,
            'start_ms': start_ms,
            'end_ms': end_ms,
            'edited': bool(node.get('edited')),
            'children': [serialize(cid, depth + 1) for cid in child_ids] if include_children else [],
            'viewpoints': viewpoints_by_node.get(nid, []) if node['level'] == 0 else [],
        }

    root_node = nodes_by_id[root_id]
    root_state = json.loads(root_node['state_json']) if root_node.get('state_json') else {}
    root_children = [cid for cid in children_map.get(root_id, []) if cid in nodes_by_id]
    is_overview_root = bool(root_children) and (root_state.get('role') == 'overview' or plan.get('need_root_overview'))

    if is_overview_root:
        overview = serialize(root_id, 0, include_children=False)
        overview['role'] = 'overview'
        top_nodes = [serialize(cid, 1) for cid in root_children]
    else:
        overview = None
        top_nodes = [serialize(root_id, 1)]

    if not plan:
        leaf_count = sum(1 for n in nodes_by_id.values() if n['level'] == 0)
        plan = {
            'leaf_count': leaf_count,
            'viewpoint_count': sum(len(v) for v in viewpoints_by_node.values()),
            'summary_layers': max(1, (root_node['level'] if is_overview_root else root_node['level'] + 1)),
            'top_count': len(top_nodes),
            'branching_factor': 1,
            'level_sizes': [leaf_count],
            'total_tokens': 0,
            'cost': 0.0,
        }

    return {
        'run_id': rid,
        'root_id': root_id,
        'plan': plan,
        'overview': overview,
        'nodes': top_nodes,
    }


def page(transcript_id, cue_after=0, card_after=0, limit=64, view_mode='auto'):
    engine.initialize()
    limit = max(1, min(64, limit))
    modes = engine.modes_status(transcript_id)
    with k.database() as db:
        row = db.execute(
            'SELECT id,title,source_kind,source,cache_key,digest,playable,media_type,asset_type,reference_kind,created_at,note_images FROM transcript WHERE id=?',
            (transcript_id,),
        ).fetchone()
        if row is None:
            raise FileNotFoundError('找不到字幕')
        active_mode = _active_mode(db, transcript_id)
        if view_mode in {'summary', 'curated', 'comprehensive'}:
            effective_mode = view_mode
        elif active_mode and modes.get(active_mode, {}).get('available'):
            effective_mode = active_mode
        else:
            effective_mode = next((m for m in ('curated', 'summary', 'comprehensive') if modes[m]['available']), active_mode or 'curated')

        cues = [
            dict(r, truncated=bool(r['truncated']))
            for r in db.execute(
                'SELECT number,start_ms,end_ms,substr(text,1,4000) AS text,length(text)>4000 AS truncated FROM cue WHERE transcript_id=? AND number>? ORDER BY number LIMIT ?',
                (transcript_id, cue_after, limit),
            )
        ]

        card_mode = effective_mode if effective_mode in {'curated', 'comprehensive'} else (
            'curated' if modes['curated']['available'] else 'comprehensive' if modes['comprehensive']['available'] else ''
        )
        if card_mode:
            card_where = "transcript_id=? AND active=1 AND (mode=? OR (note_run IS NULL AND mode IN ('', ?)))"
            card_params = (transcript_id, card_mode, card_mode)
        else:
            card_where = 'transcript_id=? AND active=1'
            card_params = (transcript_id,)

        cards = [
            dict(r, refs=json.loads(r['refs']))
            for r in db.execute(
                f'SELECT id,topic,kind,mode,claim,evidence,example,quote_translation,refs FROM card WHERE {card_where} AND id>? ORDER BY id LIMIT ?',
                (*card_params, card_after, limit),
            )
        ]
        trans_model = _preferred_translation_model(db, transcript_id)
        for cue in cues:
            cue['translation'] = translation(db, transcript_id, cue['number'], model=trans_model)
        previous = db.execute(
            f'SELECT min(id) FROM (SELECT id FROM card WHERE {card_where} AND id<=? ORDER BY id DESC LIMIT ?)',
            (*card_params, card_after, limit),
        ).fetchone()[0]
        cue_count = db.execute('SELECT count(*) FROM cue WHERE transcript_id=?', (transcript_id,)).fetchone()[0]
        card_count = db.execute(f'SELECT count(*) FROM card WHERE {card_where}', card_params).fetchone()[0]

    run_status = engine.status(transcript_id)
    lang_profile = engine.detect_document_language(transcript_id)
    tree = summary_tree(transcript_id) if modes['summary']['available'] else None
    return dict(
        row,
        cues=cues,
        cards=cards,
        cue_after=cue_after,
        card_after=card_after,
        prev_card=max(0, (previous or 1) - 1),
        next_cue=cues[-1]['number'] if len(cues) == limit else None,
        next_card=cards[-1]['id'] if len(cards) == limit else None,
        cue_count=cue_count,
        card_count=card_count,
        note_run=run_status,
        language_profile=lang_profile,
        active_mode=active_mode or effective_mode,
        view_mode=effective_mode,
        modes=modes,
        summary_tree=tree,
    )


def translation(db, transcript_id, number, offset=0, model=None):
    target_model = model or _preferred_translation_model(db, transcript_id)
    if target_model is not None:
        rows = db.execute(
            '''SELECT json_extract(t.text,'$[' || (p.local-1) || '].text') AS translated
               FROM note_translation_part p JOIN note_translation t ON p.key=t.key
               WHERE p.transcript=? AND p.model=? AND p.cue=? AND p.lo>=? AND p.lo<? ORDER BY p.lo LIMIT 16''',
            (transcript_id, target_model, number, offset, offset + 4000),
        )
    else:
        rows = db.execute(
            '''SELECT json_extract(t.text,'$[' || (p.local-1) || '].text') AS translated
               FROM note_translation_part p JOIN note_translation t ON p.key=t.key
               WHERE p.transcript=? AND p.cue=? AND p.lo>=? AND p.lo<? ORDER BY p.lo LIMIT 16''',
            (transcript_id, number, offset, offset + 4000),
        )
    parts = [r[0].strip() for r in rows if r[0] and r[0].strip()]
    return ' '.join(parts)[:4000]


def source_page(transcript_id, number, offset=0):
    with k.database() as db:
        row = db.execute(
            'SELECT number,start_ms,end_ms,substr(text,?,4000) AS text,length(text) AS size FROM cue WHERE transcript_id=? AND number=?',
            (offset + 1, transcript_id, number),
        ).fetchone()
    if row is None:
        raise FileNotFoundError('找不到原文')
    return dict(row, offset=offset, next_offset=offset + 4000 if offset + 4000 < row['size'] else None)


def node_references(transcript_id: int, node_id: int, after: int = 0) -> dict[str, Any]:
    """Bounded source span references for any node in a multi-level summary tree."""
    engine.initialize()
    with k.database() as db:
        valid = db.execute(
            'SELECT n.id FROM note_node n JOIN note_run r ON n.run=r.id WHERE n.id=? AND r.transcript_id=?',
            (node_id, transcript_id),
        ).fetchone()
        if valid is None:
            raise FileNotFoundError('找不到摘要节点')
        rows = db.execute(
            '''WITH RECURSIVE tree(id) AS (
                 SELECT ?
                 UNION ALL
                 SELECT e.child FROM note_edge e JOIN tree t ON e.parent=t.id
               ),
               spans AS (SELECT DISTINCT s.* FROM tree JOIN note_span s ON tree.id=s.node)
               SELECT s.node*100+s.local AS id,s.cue,s.lo,s.hi,c.start_ms,c.end_ms,
                      substr(c.text,s.lo+1,min(s.hi-s.lo,4000)) AS text
               FROM spans s
               JOIN cue c ON c.transcript_id=? AND c.number=s.cue
               WHERE s.node*100+s.local>? ORDER BY id LIMIT 32''',
            (node_id, transcript_id, after),
        ).fetchall()
    result = [dict(r) for r in rows]
    return {'items': result, 'next': result[-1]['id'] if len(result) == 32 else None}


def candidate_references(transcript_id: int, candidate_id: int, after: int = 0) -> dict[str, Any]:
    """Bounded source span references for a concrete viewpoint inside the summary tree."""
    engine.initialize()
    with k.database() as db:
        valid = db.execute(
            'SELECT c.id FROM note_candidate c JOIN note_run r ON c.run=r.id WHERE c.id=? AND r.transcript_id=?',
            (candidate_id, transcript_id),
        ).fetchone()
        if valid is None:
            raise FileNotFoundError('找不到观点来源')
        rows = db.execute(
            '''WITH chosen(candidate) AS (
                 SELECT ? UNION SELECT candidate FROM note_relation WHERE duplicate_of=?
               ),
               spans AS (
                 SELECT DISTINCT s.* FROM chosen c
                 JOIN note_candidate_span cs ON cs.candidate=c.candidate
                 JOIN note_span s ON cs.node=s.node AND cs.local=s.local
               )
               SELECT s.node*100+s.local AS id,s.cue,s.lo,s.hi,c.start_ms,c.end_ms,
                      substr(c.text,s.lo+1,min(s.hi-s.lo,4000)) AS text
               FROM spans s
               JOIN cue c ON c.transcript_id=? AND c.number=s.cue
               WHERE s.node*100+s.local>? ORDER BY id LIMIT 32''',
            (candidate_id, candidate_id, transcript_id, after),
        ).fetchall()
    result = [dict(r) for r in rows]
    return {'items': result, 'next': result[-1]['id'] if len(result) == 32 else None}


def references(transcript_id, card_id, after=0):
    engine.initialize()
    with k.database() as db:
        card = db.execute(
            'SELECT note_run, note_node, note_candidate, origin_key, refs FROM card WHERE transcript_id=? AND id=?',
            (transcript_id, card_id),
        ).fetchone()
        if card is None:
            raise FileNotFoundError('找不到观点')
        if card['note_candidate']:
            return candidate_references(transcript_id, card['note_candidate'], after)
        if card['note_node']:
            chapter_nodes = []
            if card['note_run'] and card['origin_key'] and ':summary:' in card['origin_key']:
                try:
                    card_idx = int(card['origin_key'].rsplit(':summary:', 1)[1])
                    chapter_nodes = [
                        r[0]
                        for r in db.execute(
                            'SELECT node FROM note_summary_node WHERE run=? AND card_index=?',
                            (card['note_run'], card_idx),
                        )
                    ]
                except ValueError:
                    chapter_nodes = []
            roots = chapter_nodes or [card['note_node']]
            placeholders = ','.join('?' for _ in roots)
            rows = db.execute(
                f'''WITH RECURSIVE tree(id) AS (
                    SELECT id FROM note_node WHERE id IN ({placeholders})
                    UNION ALL
                    SELECT e.child FROM note_edge e JOIN tree t ON e.parent=t.id),
                    spans AS (SELECT DISTINCT s.* FROM tree JOIN note_span s ON tree.id=s.node)
                    SELECT s.node*100+s.local AS id,s.cue,s.lo,s.hi,c.start_ms,c.end_ms,
                    substr(c.text,s.lo+1,min(s.hi-s.lo,4000)) AS text FROM spans s
                    JOIN cue c ON c.transcript_id=? AND c.number=s.cue
                    WHERE s.node*100+s.local>? ORDER BY id LIMIT 32''',
                (*roots, transcript_id, after),
            ).fetchall()
            result = [dict(r) for r in rows]
        else:
            result = []
            for ref in json.loads(card['refs'])[:12]:
                if ref > after:
                    row = db.execute(
                        'SELECT number AS id,number AS cue,0 AS lo,length(text) AS hi,start_ms,end_ms,substr(text,1,4000) AS text FROM cue WHERE transcript_id=? AND number=?',
                        (transcript_id, ref),
                    ).fetchone()
                    if row:
                        result.append(dict(row))
    return {'items': result, 'next': result[-1]['id'] if len(result) == 32 else None}


def _format_span_range(doc: dict[str, Any], node: dict[str, Any]) -> str:
    if doc.get('reference_kind') == 'paragraph':
        if node.get('start_cue') and node.get('end_cue'):
            return f"第 {node['start_cue']}–{node['end_cue']} 段" if node['start_cue'] != node['end_cue'] else f"第 {node['start_cue']} 段"
        return ''
    if node.get('start_ms') is not None and node.get('end_ms') is not None:
        return f"{k.clock(node['start_ms'])}–{k.clock(node['end_ms'])}"
    if node.get('start_cue') and node.get('end_cue'):
        return f"#{node['start_cue']}–#{node['end_cue']}"
    return ''


def _write_summary_markdown_node(output, doc: dict[str, Any], node: dict[str, Any], prefix: str, heading_level: int) -> None:
    hashes = '#' * min(6, max(2, heading_level))
    span_str = _format_span_range(doc, node)
    suffix = f'（{span_str}）' if span_str else ''
    output.write(f"{hashes} {prefix} {node['title']}{suffix}\n\n")
    if node.get('summary'):
        output.write(f"{node['summary']}\n\n")
    for hl in node.get('highlights') or []:
        output.write(f"- {hl}\n")
    if node.get('highlights'):
        output.write('\n')
    for idx, child in enumerate(node.get('children') or [], 1):
        _write_summary_markdown_node(output, doc, child, f'{prefix}.{idx}', heading_level + 1)
    if node.get('viewpoints'):
        for vp in node['viewpoints']:
            kind_label = engine.VIEWPOINT_KIND_LABELS.get(vp.get('kind', ''), '观点')
            output.write(f"- **[{kind_label}] {vp['claim']}**\n")
            if vp.get('quote_translation'):
                output.write(f"  - 中文译句：{vp['quote_translation']}\n")
            if vp.get('evidence'):
                output.write(f"  - 论据：{vp['evidence']}\n")
            if vp.get('example'):
                output.write(f"  - 例子：{vp['example']}\n")
            after = 0
            while True:
                refs = candidate_references(doc['id'], vp['id'], after)
                for ref in refs['items']:
                    loc = f"第 {ref['cue']} 段 · {ref['lo']}–{ref['hi']}" if doc.get('reference_kind') == 'paragraph' else f"{ref['cue']} · {k.clock(ref['start_ms'])}"
                    quote = ref['text'].replace('\n', ' ')
                    output.write(f"  - 原文 [{loc}]：{quote}\n")
                if refs['next'] is None:
                    break
                after = refs['next']
        output.write('\n')


def markdown_to(transcript_id, path, view_mode=None):
    engine.initialize()
    doc = engine.metadata(transcript_id)
    with k.database() as db:
        active = _active_mode(db, transcript_id)
    effective = view_mode if view_mode in {'summary', 'curated', 'comprehensive'} else (active or 'curated')
    if effective == 'summary':
        tree = summary_tree(transcript_id)
        if tree:
            with path.open('w', encoding='utf-8') as output:
                output.write(f"# {doc['title']}\n\n来源：{doc['source']}\n\n")
                plan = tree.get('plan') or {}
                output.write(
                    f"层级结构：{plan.get('summary_layers', 1)} 层 · "
                    f"{len(tree['nodes'])} 顶层主题 · {plan.get('leaf_count', 0)} 小节 · "
                    f"{plan.get('viewpoint_count', 0)} 底层观点\n\n"
                )
                if tree.get('overview') and tree['overview'].get('summary'):
                    output.write(f"> **全篇总览**：{tree['overview']['summary']}\n\n")
                for idx, top in enumerate(tree['nodes'], 1):
                    _write_summary_markdown_node(output, doc, top, str(idx), 2)
            return

    with path.open('w', encoding='utf-8') as output, k.database() as db:
        output.write(f"# {doc['title']}\n\n来源：{doc['source']}\n\n")
        if effective in {'curated', 'comprehensive'}:
            rows = db.execute(
                '''SELECT id,topic,kind,claim,evidence,example,quote_translation FROM card
                   WHERE transcript_id=? AND active=1
                     AND (mode=? OR (note_run IS NULL AND mode IN ('', ?)))
                   ORDER BY id''',
                (transcript_id, effective, effective),
            )
        else:
            rows = db.execute(
                'SELECT id,topic,kind,claim,evidence,example,quote_translation FROM card WHERE transcript_id=? AND active=1 ORDER BY id',
                (transcript_id,),
            )
        count = 0
        for card in rows:
            count += 1
            kind_label = engine.VIEWPOINT_KIND_LABELS.get(card['kind'] or '', '')
            prefix_parts = [p for p in (kind_label, card['topic']) if p]
            prefix = f"[{' · '.join(prefix_parts)}] " if prefix_parts else ''
            output.write(f"## {prefix}{card['claim']}\n\n")
            if card['quote_translation']:
                output.write(f"**中文译句** {card['quote_translation']}\n\n")
            for field, label in [('evidence', '论据'), ('example', '例子')]:
                if card[field]:
                    output.write(f"**{label}** {card[field]}\n\n")
            after = 0
            while True:
                refs = references(transcript_id, card['id'], after)
                for ref in refs['items']:
                    loc = (
                        f"第 {ref['cue']} 段 · {ref['lo']}–{ref['hi']}"
                        if doc.get('reference_kind') == 'paragraph'
                        else f"{ref['cue']} · {k.clock(ref['start_ms'])} · {ref['lo']}–{ref['hi']}"
                    )
                    output.write(f"> [{loc}] ")
                    for offset in range(ref['lo'], ref['hi'], 4000):
                        text = source_page(transcript_id, ref['cue'], offset)['text'][:min(4000, ref['hi'] - offset)]
                        output.write(text.replace('\n', '\n> '))
                    output.write('\n\n')
                if refs['next'] is None:
                    break
                after = refs['next']
        if not count:
            for cue in db.execute('SELECT number,length(text) AS size FROM cue WHERE transcript_id=? ORDER BY number', (transcript_id,)):
                output.write(f"\n第 {cue['number']} 段\n\n")
                for offset in range(0, cue['size'], 4000):
                    output.write(source_page(transcript_id, cue['number'], offset)['text'])
                output.write('\n')
