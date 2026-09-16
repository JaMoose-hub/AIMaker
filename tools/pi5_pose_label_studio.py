# -*- coding: utf-8 -*-
"""Model-assisted YOLO Pose label editor used by Board Vision components."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any

import numpy as np
from PIL import Image, ImageTk

from component_dataset import IMAGE_SUFFIXES
from component_labeling import extract_video_frames, import_images
from pose_labeling import (
    PoseAnnotation,
    PoseKeypoint,
    PoseLabelDataset,
    annotations_from_ultralytics_pose_result,
    box_from_keypoints,
    pose_geometry_issues,
)
from pose_registration import ReviewedPoseRegistrar


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA = ROOT / "training" / "board-pose-pi5.yaml"
DEFAULT_MODEL = (
    ROOT / "runs" / "pose" / "runs" / "board-pose" /
    "pi5-handheld-v2" / "weights" / "best.pt"
)
SETTINGS_PATH = ROOT / "training" / "pi5-pose-label-studio.json"
POINT_COLORS = (
    "#ffb347", "#49d7ff", "#67e8a5", "#ef77ff",
    "#ff6b7f", "#9fa8ff", "#f4dd57", "#65c7b7",
)


def _clone(annotation: PoseAnnotation | None) -> PoseAnnotation | None:
    return annotation.clone() if annotation is not None else None


def _settings(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


class Pi5PoseLabelStudio:
    def __init__(
        self,
        root: tk.Tk,
        initial_data: str = "",
        *,
        subject_name: str = "Raspberry Pi 5",
        settings_path: Path | str = SETTINGS_PATH,
        default_model: Path | str = DEFAULT_MODEL,
    ) -> None:
        self.root = root
        self.subject_name = subject_name.strip() or "Component"
        self.settings_path = Path(settings_path).expanduser().resolve()
        self.default_model = str(default_model)
        self.root.title(f"Board Vision - {self.subject_name} YOLO Pose 標註器")
        self.root.geometry("1500x920")
        self.root.minsize(1120, 720)
        saved = _settings(self.settings_path)
        self.dataset: PoseLabelDataset | None = None
        self.images: list[Path] = []
        self.image_index = -1
        self.current_image: Path | None = None
        self.original_image: Image.Image | None = None
        self.photo_image: ImageTk.PhotoImage | None = None
        self.annotation: PoseAnnotation | None = None
        self.selected_point = 0
        self.drag_point: int | None = None
        self.place_selected = False
        self.history: list[PoseAnnotation | None] = []
        self.redo_history: list[PoseAnnotation | None] = []
        self.dirty = False
        self.base_scale = 1.0
        self.zoom = 1.0
        self.offset_x = 0.0
        self.offset_y = 0.0
        self.model: Any = None
        self.loaded_model_path = ""
        self.single_running = False
        self.batch_running = False
        self.batch_cancel = threading.Event()
        self.closing = False

        data = initial_data or str(saved.get("data", ""))
        if not data and DEFAULT_DATA.is_file():
            data = str(DEFAULT_DATA)
        self.data_var = tk.StringVar(value=data)
        self.split_var = tk.StringVar(value=str(saved.get("split", "train")))
        self.active_split = self.split_var.get()
        self.model_var = tk.StringVar(value=str(saved.get("model", self.default_model)))
        self.confidence_var = tk.StringVar(value=str(saved.get("confidence", 0.30)))
        self.keypoint_confidence_var = tk.StringVar(
            value=str(saved.get("keypoint_confidence", 0.25))
        )
        self.auto_save_var = tk.BooleanVar(value=bool(saved.get("auto_save", True)))
        self.status_var = tk.StringVar(value="Ready")
        self.image_status_var = tk.StringVar(value="尚未開啟 Pose 資料集")
        self.progress_var = tk.StringVar(value="")
        self.geometry_var = tk.StringVar(value="")

        self._build_ui()
        self._bind_keys()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        if data and Path(data).is_file():
            self.root.after(200, lambda: self.open_dataset(data))

    def _build_ui(self) -> None:
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("Title.TLabel", font=("Microsoft JhengHei UI", 17, "bold"))
        style.configure("Strong.TLabel", font=("Microsoft JhengHei UI", 10, "bold"))
        style.configure("Primary.TButton", font=("Microsoft JhengHei UI", 10, "bold"))

        shell = ttk.Frame(self.root, padding=10)
        shell.pack(fill="both", expand=True)
        header = ttk.Frame(shell)
        header.pack(fill="x")
        ttk.Label(
            header,
            text=f"{self.subject_name} YOLO Pose 資料標註器",
            style="Title.TLabel",
        ).pack(side="left")
        ttk.Label(header, textvariable=self.image_status_var, style="Strong.TLabel").pack(
            side="right"
        )

        data_bar = ttk.Frame(shell)
        data_bar.pack(fill="x", pady=(8, 7))
        data_bar.columnconfigure(1, weight=1)
        ttk.Label(data_bar, text="Pose data.yaml").grid(row=0, column=0, padx=(0, 6))
        ttk.Entry(data_bar, textvariable=self.data_var).grid(row=0, column=1, sticky="ew")
        ttk.Button(data_bar, text="開啟", command=self.choose_dataset).grid(
            row=0, column=2, padx=(6, 0)
        )
        ttk.Button(data_bar, text="匯入圖片", command=self.import_image_folder).grid(
            row=0, column=3, padx=(6, 0)
        )
        ttk.Button(data_bar, text="影片取幀", command=self.import_video).grid(
            row=0, column=4, padx=(6, 0)
        )

        body = ttk.Panedwindow(shell, orient="horizontal")
        body.pack(fill="both", expand=True)
        center = ttk.Frame(body)
        right = ttk.Frame(body, padding=(9, 2, 0, 2), width=330)
        body.add(center, weight=1)
        body.add(right, weight=0)

        self.canvas = tk.Canvas(
            center, background="#10141b", highlightthickness=0, cursor="hand2"
        )
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _event: self.redraw())
        self.canvas.bind("<Button-1>", self.canvas_press)
        self.canvas.bind("<B1-Motion>", self.canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self.canvas_release)
        self.canvas.bind("<MouseWheel>", self.canvas_wheel)

        ttk.Label(right, text="Pose 關鍵點", style="Strong.TLabel").pack(anchor="w")
        ttk.Label(
            right,
            text="順序固定為板卡語意位置，不會隨畫面旋轉改名。",
            wraplength=305,
        ).pack(anchor="w", pady=(2, 5))
        self.point_list = tk.Listbox(right, exportselection=False, height=10, width=40)
        self.point_list.pack(fill="x")
        self.point_list.bind("<<ListboxSelect>>", self.point_selected)

        point_actions = ttk.Frame(right)
        point_actions.pack(fill="x", pady=(6, 3))
        ttk.Button(
            point_actions, text="重新放置", command=self.begin_place_selected
        ).pack(side="left", fill="x", expand=True)
        ttk.Button(
            point_actions, text="可見", command=lambda: self.set_visibility(2)
        ).pack(side="left", padx=(4, 0))
        ttk.Button(
            point_actions, text="遮擋", command=lambda: self.set_visibility(1)
        ).pack(side="left", padx=(4, 0))
        ttk.Button(
            point_actions, text="未標", command=lambda: self.set_visibility(0)
        ).pack(side="left", padx=(4, 0))

        edit_actions = ttk.Frame(right)
        edit_actions.pack(fill="x", pady=(2, 8))
        ttk.Button(edit_actions, text="上一動 Ctrl+Z", command=self.undo).pack(
            side="left", fill="x", expand=True
        )
        ttk.Button(edit_actions, text="重做 Ctrl+Y", command=self.redo).pack(
            side="left", fill="x", expand=True, padx=(4, 0)
        )
        ttk.Button(edit_actions, text="重新載入", command=self.reload_current).pack(
            side="left", fill="x", expand=True, padx=(4, 0)
        )

        auto = ttk.LabelFrame(right, text="模型自動預標", padding=8)
        auto.pack(fill="x", pady=(2, 8))
        model_row = ttk.Frame(auto)
        model_row.pack(fill="x")
        ttk.Entry(model_row, textvariable=self.model_var).pack(
            side="left", fill="x", expand=True
        )
        ttk.Button(model_row, text="…", width=3, command=self.choose_model).pack(
            side="left", padx=(4, 0)
        )
        thresholds = ttk.Frame(auto)
        thresholds.pack(fill="x", pady=(6, 3))
        ttk.Label(thresholds, text="Board").pack(side="left")
        ttk.Entry(thresholds, textvariable=self.confidence_var, width=6).pack(
            side="left", padx=(4, 10)
        )
        ttk.Label(thresholds, text="Keypoint").pack(side="left")
        ttk.Entry(
            thresholds, textvariable=self.keypoint_confidence_var, width=6
        ).pack(side="left", padx=(4, 0))
        self.prelabel_button = ttk.Button(
            auto,
            text="自動預標目前圖片",
            command=self.prelabel_current,
            style="Primary.TButton",
        )
        self.prelabel_button.pack(fill="x", pady=(5, 3))
        self.batch_button = ttk.Button(
            auto, text="批次預標所有未標圖片", command=self.batch_prelabel
        )
        self.batch_button.pack(fill="x", pady=3)
        self.registration_button = ttk.Button(
            auto,
            text="從已確認樣本預標未標圖片",
            command=self.registration_prelabel,
        )
        self.registration_button.pack(fill="x", pady=3)
        self.cancel_batch_button = ttk.Button(
            auto, text="停止批次", command=self.stop_batch, state="disabled"
        )
        self.cancel_batch_button.pack(fill="x", pady=3)
        ttk.Label(
            auto,
            text="既有 Pose label 不會被批次覆蓋；預標後必須人工確認。",
            wraplength=295,
        ).pack(anchor="w", pady=(4, 0))

        ttk.Label(
            right, textvariable=self.geometry_var, wraplength=305, foreground="#b15a20"
        ).pack(anchor="w", pady=(1, 5))
        ttk.Label(right, textvariable=self.progress_var, wraplength=305).pack(
            anchor="w", pady=(1, 6)
        )
        ttk.Button(right, text="保存草稿 Ctrl+S", command=self.save_draft).pack(
            fill="x", pady=3
        )
        ttk.Button(
            right,
            text="確認並下一張待確認",
            command=self.confirm_and_next,
            style="Primary.TButton",
        ).pack(fill="x", pady=3)
        ttk.Button(right, text="下一張未標", command=self.next_unlabeled).pack(
            fill="x", pady=3
        )
        ttk.Button(right, text="標記為負樣本", command=self.mark_negative).pack(
            fill="x", pady=(8, 3)
        )
        ttk.Checkbutton(
            right, text="換圖時自動保存", variable=self.auto_save_var
        ).pack(anchor="w", pady=(5, 0))

        navigation = ttk.Frame(shell)
        navigation.pack(fill="x", pady=(8, 0))
        ttk.Label(navigation, text="Split").pack(side="left")
        self.split_combo = ttk.Combobox(
            navigation,
            textvariable=self.split_var,
            values=("train", "val", "test"),
            state="readonly",
            width=8,
        )
        self.split_combo.pack(side="left", padx=(5, 12))
        self.split_combo.bind("<<ComboboxSelected>>", lambda _event: self.change_split())
        ttk.Button(navigation, text="◀ 上一張", command=self.previous_image).pack(
            side="left"
        )
        ttk.Button(navigation, text="下一張 ▶", command=self.next_image).pack(
            side="left", padx=(6, 0)
        )
        ttk.Label(navigation, textvariable=self.status_var).pack(side="right")

        ttk.Label(
            shell,
            text=(
                "拖曳點位即可修正；選擇點後按『重新放置』再點畫面；"
                "1–8 選擇關鍵點；滾輪縮放。"
            ),
        ).pack(anchor="w", pady=(5, 0))

    def _bind_keys(self) -> None:
        self.root.bind("<Control-s>", lambda _event: self.save_draft())
        self.root.bind("<Control-z>", lambda _event: self.undo())
        self.root.bind("<Control-y>", lambda _event: self.redo())
        self.root.bind("<Left>", lambda _event: self.previous_image())
        self.root.bind("<Right>", lambda _event: self.next_image())
        self.root.bind("<Escape>", lambda _event: self.cancel_placement())
        for index in range(8):
            self.root.bind(str(index + 1), lambda _event, value=index: self.select_point(value))

    def choose_dataset(self) -> None:
        selected = filedialog.askopenfilename(
            title="選擇 YOLO Pose data.yaml",
            filetypes=(("YOLO YAML", "*.yaml *.yml"), ("All files", "*.*")),
        )
        if selected:
            self.open_dataset(selected)

    def open_dataset(self, path: str) -> None:
        if self._work_in_progress() or not self._leave_current_image():
            return
        try:
            dataset = PoseLabelDataset(path)
        except Exception as exc:
            messagebox.showerror("Pose 資料集錯誤", str(exc))
            return
        self.dataset = dataset
        self.data_var.set(str(dataset.data_yaml))
        available = [
            split for split in ("train", "val", "test")
            if dataset.image_roots.get(split) is not None
        ]
        self.split_combo.configure(values=available)
        if self.split_var.get() not in available:
            self.split_var.set(available[0] if available else "train")
        self.active_split = self.split_var.get()
        self.change_split()
        self.status_var.set(
            f"Opened · {dataset.keypoint_count} keypoints · {dataset.class_names[0]}"
        )
        self._save_settings()

    def change_split(self) -> None:
        if self.dataset is None:
            return
        if self._work_in_progress():
            self.split_var.set(self.active_split)
            return
        if not self._leave_current_image():
            self.split_var.set(self.active_split)
            return
        self.active_split = self.split_var.get()
        self.images = self.dataset.images(self.active_split)
        self.image_index = 0 if self.images else -1
        self.load_current_image()

    def load_current_image(self) -> None:
        self.history.clear()
        self.redo_history.clear()
        self.drag_point = None
        self.place_selected = False
        if self.dataset is None or not 0 <= self.image_index < len(self.images):
            self.current_image = None
            self.original_image = None
            self.annotation = None
            self.dirty = False
            self.refresh_point_list()
            self.redraw()
            self.update_status()
            return
        self.current_image = self.images[self.image_index]
        try:
            self.original_image = Image.open(self.current_image).convert("RGB")
            annotations = self.dataset.load(self.current_image, self.active_split)
            self.annotation = annotations[0] if annotations else None
            if len(annotations) > 1:
                self.status_var.set(
                    f"此工具目前只編輯每張圖的第一個 {self.subject_name}"
                )
        except Exception as exc:
            messagebox.showerror("圖片／Pose 標籤錯誤", str(exc))
            self.original_image = None
            self.annotation = None
        if self.annotation is not None and self.dataset.review.status(
            self.dataset.key(self.current_image, self.active_split)
        ) == "auto_pending":
            self.annotation.source = "auto"
        self.selected_point = 0
        self.zoom = 1.0
        self.dirty = False
        self.refresh_point_list()
        self.redraw()
        self.update_status()

    def update_status(self) -> None:
        if self.dataset is None:
            self.image_status_var.set("尚未開啟 Pose 資料集")
            self.progress_var.set("")
            self.geometry_var.set("")
            return
        progress = self.dataset.progress(self.active_split)
        review = (
            self.dataset.review.status(self.dataset.key(self.current_image, self.active_split))
            if self.current_image is not None else "-"
        )
        index = self.image_index + 1 if self.image_index >= 0 else 0
        self.image_status_var.set(
            f"{self.active_split} · {index}/{len(self.images)} · {review}"
        )
        self.progress_var.set(
            f"總數 {progress['total']} · 已標 {progress['labeled']} · "
            f"人工確認 {progress['reviewed']} · 待確認 {progress['auto_pending']} · "
            f"未標 {progress['unlabeled']}"
        )
        issues = pose_geometry_issues(self.annotation)
        self.geometry_var.set("Pose 尚未完整：" + "；".join(issues) if issues else "Pose 幾何完整")

    def refresh_point_list(self) -> None:
        self.point_list.delete(0, "end")
        if self.dataset is None:
            return
        for index, name in enumerate(self.dataset.keypoint_names):
            if self.annotation is None:
                suffix = "未標"
            else:
                point = self.annotation.keypoints[index]
                state = {0: "未標", 1: "遮擋", 2: "可見"}.get(point.visibility, "?")
                confidence = (
                    f" · {point.confidence:.0%}" if point.confidence is not None else ""
                )
                suffix = f"{state}{confidence}"
            self.point_list.insert("end", f"{index + 1}. {name} · {suffix}")
        if 0 <= self.selected_point < self.dataset.keypoint_count:
            self.point_list.selection_set(self.selected_point)
            self.point_list.see(self.selected_point)

    def point_selected(self, _event) -> None:
        selected = self.point_list.curselection()
        if selected:
            self.selected_point = int(selected[0])
            self.redraw()

    def select_point(self, index: int) -> None:
        if self.dataset is None or not 0 <= index < self.dataset.keypoint_count:
            return
        self.selected_point = index
        self.refresh_point_list()
        self.redraw()

    def _new_annotation(self) -> PoseAnnotation:
        assert self.dataset is not None
        return PoseAnnotation(
            0,
            (0.5, 0.5, 1e-6, 1e-6),
            [PoseKeypoint(0.0, 0.0, 0) for _ in range(self.dataset.keypoint_count)],
            source="manual",
        )

    def begin_place_selected(self) -> None:
        if self._work_in_progress() or self.current_image is None:
            return
        self.place_selected = True
        self.status_var.set(
            f"請在畫面點選 {self._point_name(self.selected_point)} 的正確位置"
        )
        self.canvas.configure(cursor="crosshair")

    def cancel_placement(self) -> None:
        self.place_selected = False
        self.drag_point = None
        self.canvas.configure(cursor="hand2")
        self.status_var.set("Placement cancelled")

    def set_visibility(self, visibility: int) -> None:
        if self._work_in_progress() or self.annotation is None:
            return
        point = self.annotation.keypoints[self.selected_point]
        if visibility > 0 and point.visibility <= 0:
            self.begin_place_selected()
            return
        self._record_history()
        point.visibility = visibility
        point.confidence = None
        if visibility <= 0:
            point.x = point.y = 0.0
        self.annotation.source = "manual"
        self.dirty = True
        self.refresh_point_list()
        self.redraw()
        self.update_status()

    def _point_name(self, index: int) -> str:
        if self.dataset is None or not 0 <= index < len(self.dataset.keypoint_names):
            return f"point {index + 1}"
        return self.dataset.keypoint_names[index]

    def _record_history(self) -> None:
        self.history.append(_clone(self.annotation))
        if len(self.history) > 100:
            self.history.pop(0)
        self.redo_history.clear()

    def undo(self) -> None:
        if self._work_in_progress() or not self.history:
            return
        self.redo_history.append(_clone(self.annotation))
        self.annotation = self.history.pop()
        self.dirty = True
        self.refresh_point_list()
        self.redraw()
        self.update_status()

    def redo(self) -> None:
        if self._work_in_progress() or not self.redo_history:
            return
        self.history.append(_clone(self.annotation))
        self.annotation = self.redo_history.pop()
        self.dirty = True
        self.refresh_point_list()
        self.redraw()
        self.update_status()

    def reload_current(self) -> None:
        if self._work_in_progress() or self.current_image is None:
            return
        if self.dirty and not messagebox.askyesno("放棄修改", "重新載入並放棄目前修改？"):
            return
        self.load_current_image()

    def _canvas_to_normalized(self, x: float, y: float) -> tuple[float, float] | None:
        if self.original_image is None:
            return None
        width, height = self.original_image.size
        scale = self.base_scale * self.zoom
        nx = (x - self.offset_x) / max(width * scale, 1e-6)
        ny = (y - self.offset_y) / max(height * scale, 1e-6)
        if not 0.0 <= nx <= 1.0 or not 0.0 <= ny <= 1.0:
            return None
        return nx, ny

    def _normalized_to_canvas(self, point: tuple[float, float]) -> tuple[float, float]:
        if self.original_image is None:
            return 0.0, 0.0
        width, height = self.original_image.size
        scale = self.base_scale * self.zoom
        return (
            self.offset_x + point[0] * width * scale,
            self.offset_y + point[1] * height * scale,
        )

    def _nearest_point(self, x: float, y: float) -> int | None:
        if self.annotation is None:
            return None
        best = None
        distance_limit = 20.0
        for index, point in enumerate(self.annotation.keypoints):
            if point.visibility <= 0:
                continue
            px, py = self._normalized_to_canvas((point.x, point.y))
            distance = float(np.hypot(px - x, py - y))
            if distance < distance_limit:
                best = index
                distance_limit = distance
        return best

    def canvas_press(self, event) -> None:
        if self._work_in_progress():
            return
        normalized = self._canvas_to_normalized(event.x, event.y)
        if normalized is None or self.current_image is None or self.dataset is None:
            return
        # Closely spaced headers (for example HC-SR04's 2.54 mm pins) can be
        # less than the 20 px hit radius at fit-to-window zoom.  When the
        # currently selected keypoint is still missing, a click must create
        # that keypoint instead of selecting an adjacent point that was
        # already placed.
        selected_is_missing = (
            self.annotation is None
            or self.annotation.keypoints[self.selected_point].visibility <= 0
        )
        nearest = self._nearest_point(event.x, event.y)
        if nearest is not None and not self.place_selected and not selected_is_missing:
            self._record_history()
            self.selected_point = nearest
            self.drag_point = nearest
            self.refresh_point_list()
            return
        created = self.annotation is None
        if created:
            self._record_history()
            self.annotation = self._new_annotation()
        point = self.annotation.keypoints[self.selected_point]
        if self.place_selected or point.visibility <= 0:
            if not created:
                self._record_history()
            point.x, point.y, point.visibility = normalized[0], normalized[1], 2
            point.confidence = None
            self.annotation.source = "manual"
            self.dirty = True
            self.place_selected = False
            self.canvas.configure(cursor="hand2")
            missing = [
                index for index, item in enumerate(self.annotation.keypoints)
                if item.visibility <= 0
            ]
            if missing:
                self.selected_point = missing[0]
                self.status_var.set(f"下一點：{self._point_name(self.selected_point)}")
            else:
                self.status_var.set("全部 Pose 點已放置，可拖曳微調後確認")
            self.refresh_point_list()
            self.redraw()
            self.update_status()

    def canvas_drag(self, event) -> None:
        if self._work_in_progress() or self.drag_point is None or self.annotation is None:
            return
        normalized = self._canvas_to_normalized(event.x, event.y)
        if normalized is None:
            return
        point = self.annotation.keypoints[self.drag_point]
        point.x, point.y, point.visibility = normalized[0], normalized[1], 2
        point.confidence = None
        self.annotation.source = "manual"
        self.dirty = True
        self.redraw()

    def canvas_release(self, _event) -> None:
        if self.drag_point is not None:
            self.drag_point = None
            self.refresh_point_list()
            self.update_status()

    def canvas_wheel(self, event) -> None:
        self.zoom = min(4.0, max(0.5, self.zoom * (1.12 if event.delta > 0 else 1 / 1.12)))
        self.redraw()

    def redraw(self) -> None:
        if not hasattr(self, "canvas"):
            return
        self.canvas.delete("all")
        if self.original_image is None:
            self.canvas.create_text(
                max(self.canvas.winfo_width() / 2, 300),
                max(self.canvas.winfo_height() / 2, 200),
                text=f"開啟目前的 {self.subject_name} Pose dataset",
                fill="#9ca9b8",
                font=("Microsoft JhengHei UI", 17),
            )
            return
        canvas_width = max(100, self.canvas.winfo_width())
        canvas_height = max(100, self.canvas.winfo_height())
        image_width, image_height = self.original_image.size
        self.base_scale = min(
            (canvas_width - 24) / max(image_width, 1),
            (canvas_height - 24) / max(image_height, 1),
        )
        scale = self.base_scale * self.zoom
        display_width = max(1, int(round(image_width * scale)))
        display_height = max(1, int(round(image_height * scale)))
        self.offset_x = (canvas_width - display_width) / 2.0
        self.offset_y = (canvas_height - display_height) / 2.0
        displayed = self.original_image.resize(
            (display_width, display_height), Image.Resampling.LANCZOS
        )
        self.photo_image = ImageTk.PhotoImage(displayed)
        self.canvas.create_image(
            self.offset_x, self.offset_y, image=self.photo_image, anchor="nw"
        )
        if self.annotation is None or self.dataset is None:
            return
        first_four = self.annotation.keypoints[:4]
        if len(first_four) == 4 and all(point.visibility > 0 for point in first_four):
            polygon = [
                value
                for point in first_four
                for value in self._normalized_to_canvas((point.x, point.y))
            ]
            self.canvas.create_polygon(
                polygon,
                outline="#55e39a",
                fill="#55e39a",
                stipple="gray25",
                width=3,
            )
        visible = [point for point in self.annotation.keypoints if point.visibility > 0]
        if len(visible) >= 2:
            cx, cy, width, height = box_from_keypoints(
                self.annotation.keypoints, fallback=self.annotation.box_xywh
            )
            x1, y1 = self._normalized_to_canvas((cx - width / 2, cy - height / 2))
            x2, y2 = self._normalized_to_canvas((cx + width / 2, cy + height / 2))
            self.canvas.create_rectangle(
                x1, y1, x2, y2, outline="#8fa4bc", dash=(6, 4), width=2
            )
        for index, point in enumerate(self.annotation.keypoints):
            if point.visibility <= 0:
                continue
            x, y = self._normalized_to_canvas((point.x, point.y))
            color = POINT_COLORS[index % len(POINT_COLORS)]
            radius = 11 if index == self.selected_point else 8
            self.canvas.create_oval(
                x - radius,
                y - radius,
                x + radius,
                y + radius,
                fill=color if point.visibility == 2 else "#f0a24a",
                outline="#ffffff" if index == self.selected_point else "#121820",
                width=3,
            )
            label = f"{index + 1} {self.dataset.keypoint_names[index]}"
            if point.confidence is not None:
                label += f" {point.confidence:.0%}"
            self.canvas.create_text(
                x + 13,
                y - 11,
                text=label,
                fill="#ffffff",
                anchor="sw",
                font=("Microsoft JhengHei UI", 10, "bold"),
            )

    def _leave_current_image(self) -> bool:
        if not self.dirty or self.current_image is None:
            return True
        if self.auto_save_var.get():
            return self.save_current("draft")
        decision = messagebox.askyesnocancel("尚未保存", "保存目前 Pose 修改？")
        if decision is None:
            return False
        return self.save_current("draft") if decision else True

    def save_current(self, status: str) -> bool:
        if self.dataset is None or self.current_image is None or self._work_in_progress():
            return False
        if status != "negative":
            issues = pose_geometry_issues(self.annotation)
            if issues:
                messagebox.showwarning(
                    "Pose 尚未完整",
                    "請先修正後再保存：\n" + "\n".join(f"- {issue}" for issue in issues),
                )
                return False
        values = [] if self.annotation is None else [self.annotation]
        try:
            self.dataset.save(
                self.current_image,
                self.active_split,
                values,
                status=status,
                keypoint_count=self.dataset.keypoint_count,
            )
        except Exception as exc:
            messagebox.showerror("Pose 保存失敗", str(exc))
            return False
        self.dirty = False
        self.status_var.set(f"Saved · {status} · {self.current_image.name}")
        self.update_status()
        return True

    def save_draft(self) -> None:
        self.save_current("draft")

    def confirm_and_next(self) -> None:
        if self.save_current("reviewed"):
            self.next_pending()

    def mark_negative(self) -> None:
        if self._work_in_progress() or self.current_image is None:
            return
        if self.annotation is not None and not messagebox.askyesno(
            "標記負樣本",
            f"這會清除目前 Pose 標籤，確定畫面中沒有 {self.subject_name}？",
        ):
            return
        self._record_history()
        self.annotation = None
        self.dirty = True
        self.refresh_point_list()
        self.redraw()
        self.save_current("negative")

    def previous_image(self) -> None:
        self.navigate(-1)

    def next_image(self) -> None:
        self.navigate(1)

    def navigate(self, delta: int) -> None:
        if self._work_in_progress() or not self.images or not self._leave_current_image():
            return
        self.image_index = (self.image_index + delta) % len(self.images)
        self.load_current_image()

    def _find_next(self, predicate) -> None:
        if (
            self._work_in_progress()
            or self.dataset is None
            or not self.images
            or not self._leave_current_image()
        ):
            return
        for offset in range(1, len(self.images) + 1):
            index = (self.image_index + offset) % len(self.images)
            if predicate(self.images[index]):
                self.image_index = index
                self.load_current_image()
                return
        self.status_var.set("沒有符合條件的下一張圖片")

    def next_unlabeled(self) -> None:
        if self.dataset is None:
            return
        self._find_next(
            lambda image: not self.dataset.label_path(image, self.active_split).is_file()
        )

    def next_pending(self) -> None:
        if self.dataset is None:
            return
        self._find_next(
            lambda image: self.dataset.review.status(
                self.dataset.key(image, self.active_split)
            ) == "auto_pending"
        )

    def choose_model(self) -> None:
        selected = filedialog.askopenfilename(
            title=f"選擇 {self.subject_name} YOLO Pose 模型",
            filetypes=(("Ultralytics model", "*.pt"), ("All files", "*.*")),
        )
        if selected:
            self.model_var.set(selected)
            self.model = None
            self.loaded_model_path = ""
            self._save_settings()

    def _thresholds(self) -> tuple[float, float]:
        board = float(self.confidence_var.get())
        point = float(self.keypoint_confidence_var.get())
        if not 0.01 <= board <= 0.99 or not 0.01 <= point <= 0.99:
            raise ValueError("confidence thresholds must be between 0.01 and 0.99")
        return board, point

    def _model_path(self) -> str:
        path = str(Path(self.model_var.get()).expanduser().resolve())
        if not Path(path).is_file():
            raise FileNotFoundError(f"{self.subject_name} Pose model not found: {path}")
        return path

    def _load_model(self, path: str):
        if self.model is None or self.loaded_model_path != path:
            from ultralytics import YOLO

            self.model = YOLO(path)
            self.loaded_model_path = path
        return self.model

    def _predict(
        self,
        image: Path,
        *,
        model_path: str,
        board_threshold: float,
        point_threshold: float,
    ) -> tuple[list[PoseAnnotation], list[str]]:
        if self.dataset is None:
            return [], []
        result = self._load_model(model_path).predict(
            source=str(image), conf=board_threshold, imgsz=960, verbose=False
        )[0]
        return annotations_from_ultralytics_pose_result(
            result,
            self.dataset.class_names,
            keypoint_count=self.dataset.keypoint_count,
            keypoint_threshold=point_threshold,
        )

    def prelabel_current(self) -> None:
        if self.dataset is None or self.current_image is None or self._work_in_progress():
            return
        if self.annotation is not None and not messagebox.askyesno(
            "取代目前 Pose？",
            "模型預標會取代畫面中的 Pose；原 label 會保留 session 備份。",
        ):
            return
        try:
            model_path = self._model_path()
            board_threshold, point_threshold = self._thresholds()
        except Exception as exc:
            messagebox.showerror("預標設定錯誤", str(exc))
            return
        image = self.current_image
        self.single_running = True
        self.prelabel_button.configure(state="disabled")
        self.batch_button.configure(state="disabled")
        self.registration_button.configure(state="disabled")
        self.status_var.set(f"正在自動預標目前 {self.subject_name}…")

        def worker() -> None:
            try:
                annotations, skipped = self._predict(
                    image,
                    model_path=model_path,
                    board_threshold=board_threshold,
                    point_threshold=point_threshold,
                )
                error = None
            except Exception as exc:
                annotations, skipped, error = [], [], str(exc)
            self._post_to_ui(
                lambda: self._apply_prelabel(
                    image,
                    annotations,
                    skipped,
                    error,
                    model_path,
                    board_threshold,
                    point_threshold,
                )
            )

        threading.Thread(target=worker, daemon=True).start()

    def _apply_prelabel(
        self,
        image: Path,
        annotations: list[PoseAnnotation],
        skipped: list[str],
        error: str | None,
        model_path: str,
        board_threshold: float,
        point_threshold: float,
    ) -> None:
        self.single_running = False
        self.prelabel_button.configure(state="normal")
        self.batch_button.configure(state="normal")
        self.registration_button.configure(state="normal")
        if error:
            messagebox.showerror(f"{self.subject_name} Pose 預標失敗", error)
            self.status_var.set("Auto-label failed")
            return
        if image != self.current_image:
            return
        if not annotations:
            self.status_var.set(f"模型沒有找到 {self.subject_name}；原標籤未變更")
            return
        self._record_history()
        self.annotation = annotations[0]
        self.selected_point = 0
        self.dirty = True
        try:
            assert self.dataset is not None
            self.dataset.save(
                image,
                self.active_split,
                [self.annotation],
                status="auto_pending",
                model=model_path,
                board_confidence=self.annotation.confidence,
                board_threshold=board_threshold,
                keypoint_threshold=point_threshold,
                skipped_model_outputs=skipped,
            )
        except Exception as exc:
            messagebox.showerror("預標保存失敗", str(exc))
            self.status_var.set("Auto-label save failed")
            return
        self.dirty = False
        self.refresh_point_list()
        self.redraw()
        self.update_status()
        self.status_var.set(
            f"Pose 預標完成 · board {self.annotation.confidence or 0:.0%} · 請人工確認"
        )

    def batch_prelabel(self) -> None:
        if self.dataset is None or self._work_in_progress() or not self._leave_current_image():
            return
        targets = [
            image for image in self.images
            if not self.dataset.label_path(image, self.active_split).is_file()
        ]
        if not targets:
            messagebox.showinfo("沒有未標圖片", "目前 split 的圖片都已有 Pose label。")
            return
        if not messagebox.askyesno(
            "批次 Pose 預標",
            f"將處理 {len(targets)} 張未標圖片；既有 label 不會被覆蓋。繼續？",
        ):
            return
        try:
            model_path = self._model_path()
            board_threshold, point_threshold = self._thresholds()
        except Exception as exc:
            messagebox.showerror("預標設定錯誤", str(exc))
            return
        split = self.active_split
        self.batch_running = True
        self.batch_cancel.clear()
        self.prelabel_button.configure(state="disabled")
        self.batch_button.configure(state="disabled")
        self.registration_button.configure(state="disabled")
        self.cancel_batch_button.configure(state="normal")

        def worker() -> None:
            saved = empty = failed = 0
            try:
                self._load_model(model_path)
                for index, image in enumerate(targets, 1):
                    if self.batch_cancel.is_set():
                        break
                    try:
                        annotations, skipped = self._predict(
                            image,
                            model_path=model_path,
                            board_threshold=board_threshold,
                            point_threshold=point_threshold,
                        )
                        if annotations:
                            assert self.dataset is not None
                            self.dataset.save(
                                image,
                                split,
                                [annotations[0]],
                                status="auto_pending",
                                model=model_path,
                                board_confidence=annotations[0].confidence,
                                board_threshold=board_threshold,
                                keypoint_threshold=point_threshold,
                                skipped_model_outputs=skipped,
                            )
                            saved += 1
                        else:
                            empty += 1
                    except Exception:
                        failed += 1
                    self._post_to_ui(
                        lambda current=index, total=len(targets), count=saved: self.status_var.set(
                            f"Pose batch {current}/{total} · saved {count}"
                        )
                    )
            except Exception as exc:
                message = str(exc)
                self._post_to_ui(
                    lambda message=message: messagebox.showerror("批次預標失敗", message)
                )
            self._post_to_ui(lambda: self._batch_finished(saved, empty, failed))

        threading.Thread(target=worker, daemon=True).start()

    def stop_batch(self) -> None:
        self.batch_cancel.set()
        self.status_var.set("正在停止批次預標…")

    def registration_prelabel(self) -> None:
        if self.dataset is None or self._work_in_progress() or not self._leave_current_image():
            return
        split = self.active_split
        targets = [
            image for image in self.images
            if not self.dataset.label_path(image, split).is_file()
        ]
        if not targets:
            messagebox.showinfo("沒有未標圖片", "目前 split 的圖片都已有 Pose label。")
            return
        reviewed = sum(
            1
            for source_split in ("train", "val")
            for image in self.dataset.images(source_split)
            if self.dataset.review.status(self.dataset.key(image, source_split))
            == "reviewed"
        )
        if reviewed <= 0:
            messagebox.showwarning(
                "缺少已確認樣本",
                "請先人工確認至少一張完整的 Pose 標註。",
            )
            return
        if not messagebox.askyesno(
            "從已確認樣本預標",
            f"將用 {reviewed} 張已確認樣本配準 {len(targets)} 張未標圖片。\n"
            "只有通過幾何與配準門檻的結果會保存為待確認；繼續？",
        ):
            return
        self.batch_running = True
        self.batch_cancel.clear()
        self.prelabel_button.configure(state="disabled")
        self.batch_button.configure(state="disabled")
        self.registration_button.configure(state="disabled")
        self.cancel_batch_button.configure(state="normal")

        def progress(current: int, total: int, _image: Path, status: str) -> None:
            self._post_to_ui(
                lambda: self.status_var.set(
                    f"Pose registration {current}/{total} · {status}"
                )
            )

        def worker() -> None:
            try:
                registrar = ReviewedPoseRegistrar(self.dataset)
                summary = registrar.prelabel_unlabelled(
                    target_splits=(split,),
                    source_splits=("train", "val"),
                    apply=True,
                    cancel_event=self.batch_cancel,
                    progress=progress,
                )
                error = None
            except Exception as exc:
                summary, error = None, str(exc)
            self._post_to_ui(lambda: self._registration_finished(summary, error))

        threading.Thread(target=worker, daemon=True).start()

    def _registration_finished(self, summary, error: str | None) -> None:
        self.batch_running = False
        self.prelabel_button.configure(state="normal")
        self.batch_button.configure(state="normal")
        self.registration_button.configure(state="normal")
        self.cancel_batch_button.configure(state="disabled")
        if error:
            messagebox.showerror("幾何預標失敗", error)
            self.status_var.set("Pose registration failed")
            return
        assert summary is not None
        self.status_var.set(
            f"幾何預標完成 · 待確認 {summary.saved} · "
            f"門檻未通過 {summary.no_registration} · 失敗 {summary.failed}"
        )
        if not self.dirty:
            self.load_current_image()
        self.update_status()

    def _batch_finished(self, saved: int, empty: int, failed: int) -> None:
        self.batch_running = False
        self.prelabel_button.configure(state="normal")
        self.batch_button.configure(state="normal")
        self.registration_button.configure(state="normal")
        self.cancel_batch_button.configure(state="disabled")
        self.status_var.set(
            f"Pose batch 完成 · saved {saved} · no detection {empty} · failed {failed}"
        )
        if not self.dirty:
            self.load_current_image()
        self.update_status()

    def _current_image_root(self) -> Path | None:
        return self.dataset.image_roots.get(self.active_split) if self.dataset else None

    def import_image_folder(self) -> None:
        if self._work_in_progress():
            return
        destination = self._current_image_root()
        if destination is None:
            messagebox.showwarning("尚未開啟資料集", "請先開啟 Pose data.yaml。")
            return
        folder = filedialog.askdirectory(title=f"選擇 {self.subject_name} 圖片資料夾")
        if not folder:
            return
        sources = [
            path for path in Path(folder).rglob("*")
            if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
        ]
        if not sources:
            messagebox.showinfo("沒有圖片", "資料夾中沒有支援的圖片。")
            return
        if not messagebox.askyesno(
            "匯入 Pose 圖片", f"複製 {len(sources)} 張到 {self.active_split}？"
        ):
            return
        copied = import_images(sources, destination)
        assert self.dataset is not None
        self.images = self.dataset.images(self.active_split)
        self.status_var.set(f"Imported {len(copied)} Pose images")
        self.update_status()

    def import_video(self) -> None:
        if self._work_in_progress():
            return
        destination = self._current_image_root()
        if destination is None:
            messagebox.showwarning("尚未開啟資料集", "請先開啟 Pose data.yaml。")
            return
        video = filedialog.askopenfilename(
            title="選擇手持／多角度影片",
            filetypes=(("Video", "*.mp4 *.mov *.avi *.mkv *.m4v"), ("All files", "*.*")),
        )
        if not video:
            return
        interval = simpledialog.askfloat(
            "取幀間隔", "每隔幾秒取一張？", initialvalue=0.5, minvalue=0.05, maxvalue=30.0
        )
        if interval is None:
            return
        maximum = simpledialog.askinteger(
            "最多張數", "最多取幾張？", initialvalue=300, minvalue=1, maxvalue=5000
        )
        if maximum is None:
            return
        self.single_running = True
        self.status_var.set("正在從影片擷取 Pose 圖片…")

        def worker() -> None:
            try:
                saved = extract_video_frames(
                    video, destination, interval_s=interval, max_frames=maximum
                )
                error = None
            except Exception as exc:
                saved, error = [], str(exc)
            self._post_to_ui(lambda: self._video_finished(saved, error))

        threading.Thread(target=worker, daemon=True).start()

    def _video_finished(self, saved: list[Path], error: str | None) -> None:
        self.single_running = False
        if error:
            messagebox.showerror("影片取幀失敗", error)
            return
        if self.dataset is not None:
            self.images = self.dataset.images(self.active_split)
        self.update_status()
        self.status_var.set(f"影片取幀完成 · {len(saved)} 張未標圖片")
        messagebox.showinfo("完成", f"已加入 {len(saved)} 張，可開始批次自動預標。")

    def _work_in_progress(self) -> bool:
        if self.batch_running:
            self.status_var.set("批次 Pose 預標進行中；可先停止批次。")
            return True
        if self.single_running:
            self.status_var.set("目前正在執行模型或影片取幀，請稍候。")
            return True
        return False

    def _post_to_ui(self, callback) -> None:
        if self.closing:
            return
        try:
            self.root.after(0, callback)
        except tk.TclError:
            pass

    def _save_settings(self) -> None:
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings_path.write_text(
            json.dumps(
                {
                    "data": self.data_var.get(),
                    "split": self.active_split,
                    "model": self.model_var.get(),
                    "confidence": self.confidence_var.get(),
                    "keypoint_confidence": self.keypoint_confidence_var.get(),
                    "auto_save": self.auto_save_var.get(),
                },
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )

    def close(self) -> None:
        if self.batch_running:
            if not messagebox.askyesno("批次預標進行中", "停止批次並關閉？"):
                return
            self.batch_cancel.set()
        if self.single_running and not messagebox.askyesno(
            "背景工作進行中", "模型或影片工作尚未完成，確定關閉？"
        ):
            return
        if not self._leave_current_image():
            return
        self.closing = True
        self._save_settings()
        self.root.destroy()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default=str(DEFAULT_DATA))
    parser.add_argument("--subject", default="Raspberry Pi 5")
    parser.add_argument("--settings", default=str(SETTINGS_PATH))
    parser.add_argument("--default-model", default=str(DEFAULT_MODEL))
    args = parser.parse_args()
    root = tk.Tk()
    Pi5PoseLabelStudio(
        root,
        args.data,
        subject_name=args.subject,
        settings_path=args.settings,
        default_model=args.default_model,
    )
    root.mainloop()


if __name__ == "__main__":
    main()
