"""Execution progress consumes only validated work, across persistence and reuse."""
import json

import pytest

from app import work_progress as work


def report(record, stage, value=None, kind='progress', **kwargs):
    work.apply(record, work.event(stage, value, kind, record['execution_id']), **kwargs)
    return record['work_progress']


def test_remaining_extract_owns_the_whole_run():
    run = work.begin(work.NOTES_WEIGHTS, notes=True, excluded=['download', 'transcribe', 'translate'])
    assert report(run, 'extract', 25) == 25
    assert report(run, 'extract', 100, 'complete') == 99
    work.apply(run, status='succeeded')
    assert run['work_progress'] == 100


def test_publish_equal_weights_and_remaining_upload():
    run = work.begin(['download', 'transcribe', 'translate', 'burn', 'bilibili_upload'],
                     excluded=['download', 'transcribe', 'translate', 'burn'])
    assert report(run, 'bilibili_upload', 50) == 50


def test_notes_weights_and_runtime_skip_freeze_confirmed_work():
    run = work.begin(work.NOTES_WEIGHTS, notes=True)
    assert report(run, 'download', 100, 'complete') == 15
    assert report(run, 'transcribe', 100, 'complete') == 60
    assert report(run, 'translate', 100, 'skipped') == 60
    assert report(run, 'extract', 50) == 80


def test_shared_wait_does_not_consume_and_shared_success_redistributes():
    run = work.begin(['download', 'transcribe', 'extract'], notes=True)
    assert report(run, 'download', 100, 'complete') == 18.75
    assert report(run, 'transcribe', kind='waiting') == 18.75
    assert run['waiting_for_shared']
    assert report(run, 'transcribe', 100, 'reused') == 18.75
    assert not run['waiting_for_shared']
    assert report(run, 'extract', 50) == 59.375


def test_shared_failure_resumes_own_measured_work():
    run = work.begin(['extract'], notes=True)
    report(run, 'extract', kind='waiting')
    assert not run['work_progress_known']
    assert report(run, 'extract', 0) == 0
    assert run['work_progress_known'] and not run['waiting_for_shared']
    assert report(run, 'extract', 25) == 25


def test_partial_verified_checkpoint_counts_only_remaining_portion():
    run = work.begin(['transcribe', 'extract'], notes=True, baselines={'transcribe': 60})
    assert report(run, 'transcribe', 60) == 0
    assert report(run, 'transcribe', 80) == pytest.approx(23.6842)
    assert report(run, 'transcribe', 100, 'complete') == pytest.approx(47.3684)


def test_persistence_out_of_order_and_failed_retry_identity():
    run = work.begin(['extract'], notes=True)
    report(run, 'extract', 50)
    restored = json.loads(json.dumps(run))
    assert report(restored, 'extract', 5) == 50
    work.apply(restored, status='failed')
    assert restored['work_progress'] == 50
    retry = work.begin(['extract'], notes=True)
    assert retry['execution_id'] != restored['execution_id']
    work.apply(retry, work.event('extract', 100, 'complete', restored['execution_id']))
    assert retry['work_progress'] == 0 and not retry['work_progress_known']


def test_invalidated_cache_is_reallocated_without_rewind():
    run = work.begin(['download', 'transcribe', 'extract'], notes=True, excluded=['transcribe'])
    first = report(run, 'download', 100, 'complete')
    assert report(run, 'transcribe', 0) == first
    assert first < report(run, 'transcribe', 50) < 99


def test_everything_reused_has_no_artificial_consumption():
    run = work.begin(['download', 'transcribe', 'extract'], notes=True, excluded=['download', 'transcribe', 'extract'])
    for stage in ['download', 'transcribe', 'extract']:
        assert report(run, stage, 100, 'reused') == 0
    work.apply(run, status='succeeded')
    assert run['work_progress'] == 100


def test_legacy_record_remains_legacy():
    record = {'progress': 40}
    work.apply(record, work.event('transcribe', 50), status='running')
    assert record == {'progress': 40}
