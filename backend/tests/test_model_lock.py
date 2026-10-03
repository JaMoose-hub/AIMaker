"""All consumers synchronize on the owner, including close during inference."""
import threading
from concurrent.futures import ThreadPoolExecutor

from app.vision.model_lock import serialized_model_call


def test_model_owner_serializes_two_sources_and_close():
    entered, release = threading.Event(), threading.Event()
    calls = []

    class Owner:
        @serialized_model_call
        def locate(self, source):
            calls.append(source)
            if source == "webcam":
                entered.set()
                assert release.wait(3)

        @serialized_model_call
        def close(self):
            calls.append("close")

    owner = Owner()
    with ThreadPoolExecutor(3) as pool:
        webcam = pool.submit(owner.locate, "webcam")
        assert entered.wait(3)
        phone = pool.submit(owner.locate, "phone")
        close = pool.submit(owner.close)
        assert calls == ["webcam"]
        release.set()
        webcam.result(3)
        phone.result(3)
        close.result(3)
    assert sorted(calls) == ["close", "phone", "webcam"]
