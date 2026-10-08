"""Slow workflow persistence must not block native phone frame receipt."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import threading

import pytest

from app import mobile
from test_mobile import context, setup


@pytest.mark.parametrize('component', ['hc-sr04', 'mrd-tf240-8p-cs'])
def test_test_state_save_does_not_hold_media_lock(setup, monkeypatch, component):
    service, phone, clock = setup
    sid = phone['session_id']
    stream = asyncio.run(service.start_stream(sid))
    generation = stream['generation']
    payload = context()
    payload['context']['debug_context'] = {'entry': {'component_id': component, 'runId': 'new-test'}}
    saving, release = threading.Event(), threading.Event()
    write = mobile._write_json

    def slow_write(path, record):
        saving.set()
        assert release.wait(3), 'test did not release workflow persistence'
        write(path, record)

    monkeypatch.setattr(mobile, '_write_json', slow_write)
    with ThreadPoolExecutor(max_workers=2) as pool:
        publication = pool.submit(service.publish_context, payload)
        try:
            assert saving.wait(2)
            receipt = pool.submit(service.on_receive, sid, generation, 10, clock.now, clock.wall(), (1920, 1080))
            receipt.result(timeout=.5)
            assert service.snapshot(sid)['stream']['received_frames'] == 10
        finally:
            release.set()
        publication.result(timeout=2)
    assert service.snapshot(sid)['stream']['generation'] == generation
    assert service.snapshot(sid)['stream']['active']
    assert service.rtc.closed == []


def test_failed_workflow_save_does_not_publish_partial_context(setup, monkeypatch):
    service, phone, _ = setup
    before = deepcopy(service.latest)
    contexts = set(service.contexts)
    def fail(*args):
        raise OSError('disk temporarily unavailable')
    monkeypatch.setattr(mobile, '_write_json', fail)
    with pytest.raises(OSError):
        service.publish_context(context(title='Changed project'))
    assert service.latest == before
    assert set(service.contexts) == contexts
    assert service.snapshot(phone['session_id'])['context_id'] == before['context_id']


def test_concurrent_publications_commit_in_persistence_order(setup, monkeypatch):
    service, _, _ = setup
    entered, release, second_called = threading.Event(), threading.Event(), threading.Event()
    written = []
    write = mobile._write_json
    def ordered_write(path, record):
        if record['title'] == 'first':
            entered.set()
            assert release.wait(3)
        written.append(record['title'])
        write(path, record)
    def second():
        second_called.set()
        return service.publish_context(context(title='second'))
    monkeypatch.setattr(mobile, '_write_json', ordered_write)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(service.publish_context, context(title='first'))
        try:
            assert entered.wait(2)
            later = pool.submit(second)
            assert second_called.wait(2)
        finally:
            release.set()
        first.result(timeout=2)
        last = later.result(timeout=2)
    assert written == ['first', 'second']
    assert service.latest['context_id'] == last['context_id']
