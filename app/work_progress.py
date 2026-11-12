"""Persisted progress for the work in one execution, independent of legacy progress.

Only measured stage events consume paper. Reuse/skip rebases the unconsumed
budget, preserving the confirmed amount. A new execution is the only reset.
"""
import copy
import uuid

NOTES_WEIGHTS = {'download': 15, 'transcribe': 45, 'translate': 20, 'extract': 20}
PUBLIC_FIELDS = ('execution_id', 'work_progress', 'work_progress_known', 'waiting_for_shared')


def begin(stages, *, notes=False, execution_id=None, baselines=None, excluded=()):
    baselines = baselines or {}
    steps = {name: {'weight': NOTES_WEIGHTS.get(name, 1) if notes else 1,
                    'baseline': float(baselines.get(name, 0)),
                    'local': float(baselines.get(name, 0)),
                    'state': 'excluded' if name in excluded else 'pending'} for name in stages}
    return {'execution_id': execution_id or uuid.uuid4().hex,
            'work_progress': 0.0, 'work_progress_known': False, 'waiting_for_shared': False,
            'work_plan': {'version': 1, 'anchor': 0.0, 'steps': steps}}


def apply(record, event=None, *, status=None):
    if not record.get('execution_id'):
        return
    event = event or {}
    if event.get('execution_id') and event['execution_id'] != record['execution_id']:
        return
    plan = copy.deepcopy(record.get('work_plan') or {})
    steps = plan.get('steps', {})
    stage, kind = event.get('stage'), event.get('kind', 'progress')
    if stage in steps:
        step = steps[stage]
        if kind == 'waiting':
            record['waiting_for_shared'] = True
        elif kind in {'reused', 'skipped'}:
            record['waiting_for_shared'] = False
            step['state'] = 'excluded'
            # Freeze confirmed progress; redistribute only work still to do.
            plan['anchor'] = float(record.get('work_progress') or 0) / 100
            for remaining in steps.values():
                remaining['baseline'] = remaining['local']
                if remaining['local'] >= 100:
                    remaining['state'] = 'excluded'
        elif kind in {'progress', 'complete'}:
            record['waiting_for_shared'] = False
            if step['state'] == 'excluded':
                # A preflight artifact was invalidated before use. Budget it now.
                step.update(state='pending', local=0.0, baseline=0.0)
                plan['anchor'] = float(record.get('work_progress') or 0) / 100
                for remaining in steps.values():
                    remaining['baseline'] = remaining['local']
            value = 100 if kind == 'complete' else event.get('value')
            if value is not None:
                step['local'] = max(step['local'], max(0, min(100, float(value))))
                step['state'] = 'done' if step['local'] == 100 else 'running'
                record['work_progress_known'] = True
    budget = sum(s['weight'] * (100 - s['baseline']) for s in steps.values() if s['state'] != 'excluded')
    consumed = sum(s['weight'] * (s['local'] - s['baseline']) for s in steps.values() if s['state'] != 'excluded')
    if budget:
        value = 100 * (plan.get('anchor', 0) + (1 - plan.get('anchor', 0)) * consumed / budget)
        record['work_progress'] = round(max(float(record.get('work_progress') or 0), min(99, value)), 4)
    if status == 'succeeded':
        record.update(work_progress=100.0, work_progress_known=True, waiting_for_shared=False)
    elif status in {'failed', 'cancelled', 'blocked'}:
        record['waiting_for_shared'] = False
    record['work_plan'] = plan


def event(stage, value=None, kind='progress', execution_id=None):
    return {'stage': stage, 'value': value, 'kind': kind, 'execution_id': execution_id}
