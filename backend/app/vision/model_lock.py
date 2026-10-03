"""Serialize inference and close at the model owner, across all frame sources."""
from functools import wraps
import threading

_creation_lock = threading.Lock()


def serialized_model_call(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        lock = getattr(self, "_inference_lock", None)
        if lock is None:
            with _creation_lock:
                lock = getattr(self, "_inference_lock", None)
                if lock is None:
                    lock = self._inference_lock = threading.RLock()
        with lock:
            return method(self, *args, **kwargs)
    return call
