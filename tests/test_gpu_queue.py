import threading
import time

from app import gpu_queue


def test_fifo_and_exception_release():
    order = []
    workers = []
    def work(index):
        with gpu_queue.slot():
            order.append(index)
    with gpu_queue.slot():
        for index in range(4):
            thread = threading.Thread(target=work, args=(index,))
            workers.append(thread)
            thread.start()
            deadline = time.monotonic() + 2
            while True:
                with gpu_queue._condition:
                    queued = len(gpu_queue._waiting)
                if queued == index + 2:
                    break
                assert time.monotonic() < deadline
                time.sleep(.001)
    for thread in workers:
        thread.join(2)
        assert not thread.is_alive()
    assert order == list(range(4))
    try:
        with gpu_queue.slot():
            raise ValueError('worker failed')
    except ValueError:
        pass
    assert not gpu_queue._waiting


def test_cancelled_admission_releases_ticket():
    try:
        with gpu_queue.slot(cancelled=lambda: True):
            raise AssertionError('cancelled job admitted')
    except RuntimeError:
        pass
    assert not gpu_queue._waiting


def test_lane_fair_round_robin_between_notes_and_publish():
    order = []
    workers = []

    def work(lane, name):
        with gpu_queue.slot(lane=lane, operation='gpu', cooldown=0.0):
            order.append(name)

    def enqueue(lane, name, expected_total):
        thread = threading.Thread(target=work, args=(lane, name))
        workers.append(thread)
        thread.start()
        deadline = time.monotonic() + 2
        while True:
            with gpu_queue._condition:
                queued = len(gpu_queue._waiting)
            if queued == expected_total:
                break
            assert time.monotonic() < deadline
            time.sleep(0.001)

    with gpu_queue.slot(lane='publish', operation='gpu', cooldown=0.0):
        enqueue('publish', 'publish-1', 2)
        enqueue('publish', 'publish-2', 3)
        enqueue('notes', 'notes-1', 4)
        enqueue('publish', 'publish-3', 5)
        enqueue('notes', 'notes-2', 6)

    for thread in workers:
        thread.join(2)
        assert not thread.is_alive()

    assert order == ['notes-1', 'publish-1', 'notes-2', 'publish-2', 'publish-3']
    assert not gpu_queue._waiting


def test_wait_callback_and_snapshot():
    events = []
    ready = threading.Event()

    def waiter():
        with gpu_queue.slot(
            lane='notes',
            operation='transcribe',
            cooldown=0.0,
            on_wait=lambda pos, holder: (events.append((pos, holder)), ready.set()),
        ):
            pass

    with gpu_queue.slot(lane='publish', operation='burn', label='job-1', cooldown=0.0):
        thread = threading.Thread(target=waiter)
        thread.start()
        assert ready.wait(2)
        snap = gpu_queue.snapshot(include_vram=False)
        assert snap['busy'] is True
        assert snap['holder']['lane'] == 'publish'
        assert snap['holder']['operation'] == 'burn'
        assert snap['waiting_count'] == 1
        assert snap['waiting_by_lane']['notes'] == 1
    thread.join(2)
    assert not thread.is_alive()
    assert events and events[0][0] == 1
    assert events[0][1]['lane'] == 'publish'
    assert events[0][1]['operation'] == 'burn'
    assert gpu_queue.snapshot(include_vram=False)['busy'] is False


def test_vram_adaptive_whisper_plan():
    abundant = gpu_queue.plan_whisper_gpu('small', 8, vram={'total_mb': 12288, 'free_mb': 10000, 'used_mb': 2288})
    assert abundant['mode'] == 'batched' and abundant['batch_size'] == 8

    moderate = gpu_queue.plan_whisper_gpu('large-v3-turbo', 8, vram={'total_mb': 8192, 'free_mb': 5500, 'used_mb': 2692})
    assert moderate['mode'] == 'batched' and moderate['batch_size'] == 4

    tight = gpu_queue.plan_whisper_gpu('large-v3-turbo', 8, vram={'total_mb': 8192, 'free_mb': 4400, 'used_mb': 3792})
    assert tight['mode'] == 'batched' and tight['batch_size'] == 2

    low = gpu_queue.plan_whisper_gpu('large-v3', 8, vram={'total_mb': 6144, 'free_mb': 5200, 'used_mb': 944})
    assert low['mode'] == 'batched' and low['batch_size'] == 1

    minimal = gpu_queue.plan_whisper_gpu('large-v3', 8, vram={'total_mb': 6144, 'free_mb': 4900, 'used_mb': 1244})
    assert minimal['mode'] == 'standard' and minimal['batch_size'] == 1


def test_release_cooldown_enforces_gap():
    timestamps = []
    entered = threading.Event()

    def second():
        entered.set()
        with gpu_queue.slot(lane='notes', operation='gpu', cooldown=0.0):
            timestamps.append(time.perf_counter())

    with gpu_queue.slot(lane='publish', operation='gpu', cooldown=0.06):
        thread = threading.Thread(target=second)
        thread.start()
        assert entered.wait(2)
        time.sleep(0.01)
        released_at = time.perf_counter()
    thread.join(2)
    assert not thread.is_alive()
    assert timestamps and timestamps[0] - released_at >= 0.04
    assert not gpu_queue._waiting
