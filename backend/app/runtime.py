"""Atomic board-runtime switching while the camera service keeps running."""
from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from app.query.service import QueryService


class RuntimeSwitchError(Exception):
    def __init__(self, error_code: str, **params: object) -> None:
        self.error_code = error_code
        self.params = params
        super().__init__(error_code)


@dataclass(frozen=True)
class RuntimeSnapshot:
    board_id: str
    runtime_revision: int


class BoardRuntimeManager:
    """Owns the active profile/detector/query-service tuple.

    Candidate models are fully constructed before the short commit section.
    VisionWorker serializes the swap against in-flight inference, so closing
    the replaced detector cannot invalidate a frame that is still using it.
    """

    def __init__(
        self,
        *,
        config,
        profile_store,
        detector_builder: Callable[[Any, Path, Any], Any],
    ) -> None:
        self._config = config
        self._store = profile_store
        self._detector_builder = detector_builder
        self._lock = threading.RLock()
        self._switch_lock = threading.Lock()
        self._active_board_id = str(config.board)
        self._revision = int(config.runtime_revision)

    def snapshot(self) -> RuntimeSnapshot:
        with self._lock:
            return RuntimeSnapshot(self._active_board_id, self._revision)

    @property
    def board_id(self) -> str:
        return self.snapshot().board_id

    @property
    def runtime_revision(self) -> int:
        return self.snapshot().runtime_revision

    def profile(self):
        return self._store.profile(self.board_id)

    def camera_changed(self, state) -> int:
        """Publish a fresh frame/pose context after a stopped camera is replaced."""
        with self._switch_lock:
            with self._lock:
                self._revision += 1
                self._config.runtime_revision = self._revision
                revision = self._revision
                board_id = self._active_board_id
            state.vision_worker.set_detector(
                state.detector, board_id=board_id, runtime_revision=revision,
            )
            state.broadcaster.publish_threadsafe({
                "type": "runtime_changed", "board_id": board_id,
                "runtime_revision": revision,
            })
            return revision

    def controllers(self) -> dict[str, object]:
        current = self.snapshot()
        controllers: list[dict[str, object]] = []
        for board_id in self._store.available_boards():
            profile = self._store.profile(board_id)
            selected_model = self._config.yolo_pose.model_path_for(board_id)
            preferred_8pt = self._config.yolo_pose.board_8pt_model_paths.get(board_id)
            keypoint_count = self._config.yolo_pose.keypoint_count_for(board_id)
            controllers.append({
                "board_id": board_id,
                "name": dict(profile.board.name),
                "active": board_id == current.board_id,
                "model": {
                    "path": str(selected_model),
                    "ready": selected_model.is_file(),
                    "keypoint_count": keypoint_count,
                    "preferred_8pt_path": str(preferred_8pt) if preferred_8pt else None,
                    "preferred_8pt_ready": bool(
                        preferred_8pt is not None and preferred_8pt.is_file()
                    ),
                    "fallback_active": bool(
                        preferred_8pt is not None and not preferred_8pt.is_file()
                    ),
                },
                "pose_landmarks": len(profile.resolved_pose_landmarks()),
                "wiring_guide_available": board_id in {
                    "arduino-uno-q", "raspberry-pi-5"
                },
                "electrical_verification_available": bool(
                    board_id == "arduino-uno-q"
                    and self._config.electrical_verification.enabled
                ),
            })
        return {
            "controllers": controllers,
            "current_board_id": current.board_id,
            "runtime_revision": current.runtime_revision,
        }

    def select(self, board_id: str, state, *, force: bool = False) -> dict[str, object]:
        requested = str(board_id).strip()
        if not requested:
            raise RuntimeSwitchError("controller_id_required")
        with self._switch_lock:
            before = self.snapshot()
            if requested == before.board_id and not force:
                return {
                    "ok": True,
                    "changed": False,
                    "board_id": before.board_id,
                    "runtime_revision": before.runtime_revision,
                    "guide_was_active": False,
                }
            if requested not in self._store.available_boards():
                raise RuntimeSwitchError(
                    "controller_not_found", board_id=requested
                )

            candidate = None
            try:
                profile = self._store.profile(requested)
                profile_dir = self._store.board_dir(requested)
                candidate = self._detector_builder(
                    profile, profile_dir, getattr(state, "scene", None)
                )
                candidate_query_service = QueryService(
                    profile, self._config.default_locale
                )
                selected_model = self._config.yolo_pose.model_path_for(requested)
                if (
                    self._config.detector == "hybrid"
                    and requested != "arduino-uno-q"
                    and selected_model.is_file()
                    and hasattr(candidate, "primary")
                    and not bool(candidate.primary.available)
                ):
                    try:
                        candidate.close()
                    except Exception:
                        pass
                    raise RuntimeError("selected pose model did not load")
            except Exception as exc:
                if candidate is not None:
                    try:
                        candidate.close()
                    except Exception:
                        pass
                raise RuntimeSwitchError(
                    "controller_model_load_failed",
                    board_id=requested,
                    reason=type(exc).__name__,
                ) from exc

            guide_was_active = state.guidance_state.get_step() is not None
            next_revision = before.runtime_revision + 1
            old_detector = state.detector
            old_profile = state.profile
            old_query_service = state.query_service
            workers = [
                worker
                for worker_name in (
                    "wire_worker",
                    "insertion_vlm_worker",
                    "final_wiring_vlm_worker",
                    "electrical_worker",
                )
                if (worker := getattr(state, worker_name, None)) is not None
                and hasattr(worker, "set_board_id")
            ]
            switched_workers: list[object] = []
            try:
                state.vision_worker.set_detector(
                    candidate,
                    board_id=requested,
                    runtime_revision=next_revision,
                )
                for worker in workers:
                    worker.set_board_id(requested)
                    switched_workers.append(worker)
            except Exception:
                # Candidate preparation succeeded but a runtime participant
                # rejected the hand-over. Roll every participant back before
                # exposing any manager/config/profile change.
                for worker in reversed(switched_workers):
                    try:
                        worker.set_board_id(before.board_id)
                    except Exception:
                        pass
                try:
                    state.vision_worker.set_detector(
                        old_detector,
                        board_id=before.board_id,
                        runtime_revision=before.runtime_revision,
                    )
                except Exception:
                    pass
                state.profile = old_profile
                state.detector = old_detector
                state.query_service = old_query_service
                try:
                    candidate.close()
                except Exception:
                    pass
                raise RuntimeSwitchError(
                    "controller_switch_commit_failed", board_id=requested
                )

            # All fallible participants accepted the candidate. Publish the
            # coherent tuple under one lock, then clear board-specific output
            # snapshots before announcing the new revision.
            with self._lock:
                self._active_board_id = requested
                self._revision = next_revision
                # Keep legacy route/worker readers coherent while the runtime
                # manager remains the authoritative owner.
                self._config.board = requested
                self._config.runtime_revision = next_revision
                state.profile = profile
                state.detector = candidate
                state.query_service = candidate_query_service

            state.detection_state.clear()
            state.wire_state.clear()
            state.guidance_state.clear()
            state.verification_state.clear()
            preview = getattr(state, "guidance_color_preview", None)
            if preview is not None and hasattr(preview, "clear"):
                preview.clear()

            state.broadcaster.publish_threadsafe({
                "type": "runtime_changed",
                "board_id": requested,
                "runtime_revision": next_revision,
            })
            if old_detector is not None and old_detector is not candidate:
                try:
                    old_detector.close()
                except Exception:
                    pass
            return {
                "ok": True,
                "changed": True,
                "board_id": requested,
                "runtime_revision": next_revision,
                "guide_was_active": guide_was_active,
            }
