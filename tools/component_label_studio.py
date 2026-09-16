# -*- coding: utf-8 -*-
"""Interactive YOLO component annotation and model-assisted pre-labeling GUI."""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageTk

from component_dataset import IMAGE_SUFFIXES
from component_labeling import (
    Annotation,
    ComponentLabelDataset,
    annotations_from_ultralytics_result,
    clone_annotations,
    create_component_dataset,
    extract_video_frames,
    import_images,
)


ROOT = Path(__file__).resolve().parent.parent
SETTINGS_PATH = ROOT / "training" / "component-label-studio.json"
DEFAULT_MODEL = (
    ROOT / "runs" / "segment" / "runs" / "components" /
    "pi5-components-seg-v1" / "weights" / "best.pt"
)
PALETTE = (
    "#46d7ff", "#ffb44a", "#63e6a5", "#ff6f91", "#b58cff",
    "#f7df5e", "#5aa7ff", "#ff845e", "#7ee787", "#e879f9",
)


def _load_settings() -> dict[str, Any]:
    if not SETTINGS_PATH.is_file():
        return {}
    try:
        payload = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


class ComponentLabelStudio:
    def __init__(self, root: tk.Tk, initial_data: str = "") -> None:
        self.root = root
        self.root.title("Board Vision - 零件資料標註器 / Component Label Studio")
        self.root.geometry("1500x920")
        self.root.minsize(1120, 720)
        settings = _load_settings()
        self.dataset: ComponentLabelDataset | None = None
        self.images: list[Path] = []
        self.image_index = -1
        self.current_image: Path | None = None
        self.original_image: Image.Image | None = None
        self.photo_image: ImageTk.PhotoImage | None = None
        self.annotations: list[Annotation] = []
        self.selected_annotation = -1
        self.working_points: list[tuple[float, float]] = []
        self.drag_box_start: tuple[float, float] | None = None
        self.drag_vertex: tuple[int, int] | None = None
        self.history: list[list[Annotation]] = []
        self.redo_history: list[list[Annotation]] = []
        self.dirty = False
        self.base_scale = 1.0
        self.zoom = 1.0
        self.offset_x = 0.0
        self.offset_y = 0.0
        self.prelabel_model: Any = None
        self.prelabel_model_loaded_path = ""
        self.batch_cancel = threading.Event()
        self.batch_running = False
        self.single_prelabel_running = False
        self.closing = False

        default_data = initial_data or settings.get("data", "")
        if not default_data:
            candidate = Path.home() / "Downloads" / "pi5_data" / "data.yaml"
            default_data = str(candidate) if candidate.is_file() else ""
        self.data_var = tk.StringVar(value=default_data)
        self.split_var = tk.StringVar(value=settings.get("split", "train"))
        self.active_split = self.split_var.get()
        self.mode_var = tk.StringVar(value=settings.get("mode", "polygon"))
        self.auto_save_var = tk.BooleanVar(value=bool(settings.get("auto_save", True)))
        self.model_var = tk.StringVar(value=settings.get("model", str(DEFAULT_MODEL)))
        self.confidence_var = tk.StringVar(value=str(settings.get("confidence", 0.30)))
        self.image_status_var = tk.StringVar(value="尚未開啟資料集")
        self.progress_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="Ready")

        self._build_ui()
        self._bind_keys()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        if self.data_var.get() and Path(self.data_var.get()).is_file():
            self.root.after(250, lambda: self.open_dataset(self.data_var.get()))

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
        ttk.Label(header, text="零件資料標註器  Component Label Studio", style="Title.TLabel").pack(side="left")
        ttk.Label(header, textvariable=self.image_status_var, style="Strong.TLabel").pack(side="right")

        dataset_bar = ttk.Frame(shell)
        dataset_bar.pack(fill="x", pady=(8, 8))
        dataset_bar.columnconfigure(1, weight=1)
        ttk.Label(dataset_bar, text="data.yaml").grid(row=0, column=0, padx=(0, 6))
        ttk.Entry(dataset_bar, textvariable=self.data_var).grid(row=0, column=1, sticky="ew")
        ttk.Button(dataset_bar, text="開啟", command=self.choose_dataset).grid(row=0, column=2, padx=(6, 0))
        ttk.Button(dataset_bar, text="建立新資料集", command=self.create_dataset).grid(row=0, column=3, padx=(6, 0))
        ttk.Button(dataset_bar, text="匯入圖片資料夾", command=self.import_image_folder).grid(row=0, column=4, padx=(6, 0))
        ttk.Button(dataset_bar, text="影片取幀", command=self.import_video).grid(row=0, column=5, padx=(6, 0))

        body = ttk.Panedwindow(shell, orient="horizontal")
        body.pack(fill="both", expand=True)

        left = ttk.Frame(body, padding=(0, 4, 8, 4), width=220)
        center = ttk.Frame(body, padding=0)
        right = ttk.Frame(body, padding=(8, 4, 0, 4), width=300)
        body.add(left, weight=0)
        body.add(center, weight=1)
        body.add(right, weight=0)

        ttk.Label(left, text="類別 Classes", style="Strong.TLabel").pack(anchor="w")
        self.class_list = tk.Listbox(left, exportselection=False, width=24, height=18)
        self.class_list.pack(fill="both", expand=True, pady=(5, 8))
        self.class_list.bind("<<ListboxSelect>>", lambda _event: self.redraw())
        ttk.Label(left, text="標註模式", style="Strong.TLabel").pack(anchor="w", pady=(3, 3))
        for text, value in (("多邊形 Polygon", "polygon"), ("矩形 Box", "box"), ("編輯頂點 Edit", "edit")):
            ttk.Radiobutton(left, text=text, value=value, variable=self.mode_var, command=self._mode_changed).pack(anchor="w")
        ttk.Button(left, text="完成多邊形  Enter", command=self.finish_polygon).pack(fill="x", pady=(8, 3))
        ttk.Button(left, text="上一動  Ctrl+Z", command=self.undo).pack(fill="x", pady=3)
        ttk.Button(left, text="刪除選取  Delete", command=self.delete_selected).pack(fill="x", pady=3)
        ttk.Button(left, text="清除全部", command=self.clear_all).pack(fill="x", pady=3)
        ttk.Button(left, text="標記為負樣本", command=self.mark_negative).pack(fill="x", pady=(10, 3))
        ttk.Checkbutton(left, text="換圖時自動保存", variable=self.auto_save_var).pack(anchor="w", pady=(8, 0))

        self.canvas = tk.Canvas(center, background="#11151c", highlightthickness=0, cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _event: self.redraw())
        self.canvas.bind("<Button-1>", self.canvas_press)
        self.canvas.bind("<B1-Motion>", self.canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self.canvas_release)
        self.canvas.bind("<Button-3>", self.canvas_right_click)
        self.canvas.bind("<MouseWheel>", self.canvas_wheel)

        ttk.Label(right, text="標註 Annotations", style="Strong.TLabel").pack(anchor="w")
        self.annotation_list = tk.Listbox(right, exportselection=False, width=34, height=13)
        self.annotation_list.pack(fill="x", pady=(5, 8))
        self.annotation_list.bind("<<ListboxSelect>>", self.annotation_selected)

        auto_box = ttk.LabelFrame(right, text="自動預標 Auto-label", padding=8)
        auto_box.pack(fill="x", pady=(5, 8))
        ttk.Label(auto_box, text="模型 .pt/.onnx").pack(anchor="w")
        model_row = ttk.Frame(auto_box)
        model_row.pack(fill="x", pady=(3, 6))
        ttk.Entry(model_row, textvariable=self.model_var).pack(side="left", fill="x", expand=True)
        ttk.Button(model_row, text="…", width=3, command=self.choose_prelabel_model).pack(side="left", padx=(4, 0))
        confidence_row = ttk.Frame(auto_box)
        confidence_row.pack(fill="x")
        ttk.Label(confidence_row, text="信心門檻").pack(side="left")
        ttk.Entry(confidence_row, textvariable=self.confidence_var, width=7).pack(side="left", padx=(6, 0))
        self.prelabel_button = ttk.Button(
            auto_box, text="預標目前圖片", command=self.prelabel_current, style="Primary.TButton"
        )
        self.prelabel_button.pack(fill="x", pady=(8, 3))
        self.batch_button = ttk.Button(auto_box, text="批次預標所有未標圖片", command=self.batch_prelabel)
        self.batch_button.pack(fill="x", pady=3)
        self.cancel_batch_button = ttk.Button(
            auto_box, text="停止批次", command=self.stop_batch, state="disabled"
        )
        self.cancel_batch_button.pack(fill="x", pady=3)
        ttk.Label(
            auto_box,
            text="不覆蓋既有 label；結果先標為待確認。",
            wraplength=260,
        ).pack(anchor="w", pady=(5, 0))

        ttk.Label(right, textvariable=self.progress_var, wraplength=270).pack(anchor="w", pady=(4, 6))
        ttk.Button(right, text="保存草稿  Ctrl+S", command=self.save_draft).pack(fill="x", pady=3)
        ttk.Button(
            right,
            text="確認並下一張待確認",
            command=self.confirm_and_next,
            style="Primary.TButton",
        ).pack(fill="x", pady=3)
        ttk.Button(right, text="下一張未標", command=self.next_unlabeled).pack(fill="x", pady=3)

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
        ttk.Button(navigation, text="◀ 上一張", command=self.previous_image).pack(side="left")
        ttk.Button(navigation, text="下一張 ▶", command=self.next_image).pack(side="left", padx=(6, 0))
        ttk.Label(navigation, textvariable=self.status_var).pack(side="right")

        ttk.Label(
            shell,
            text="左鍵加點／拖矩形；右鍵回復目前多邊形上一點；Enter 完成；Edit 模式拖曳頂點；1–9 選類別。",
        ).pack(anchor="w", pady=(5, 0))

    def _bind_keys(self) -> None:
        self.root.bind("<Control-s>", lambda _event: self.save_draft())
        self.root.bind("<Control-z>", lambda _event: self.undo())
        self.root.bind("<Control-y>", lambda _event: self.redo())
        self.root.bind("<Delete>", lambda _event: self.delete_selected())
        self.root.bind("<Return>", lambda _event: self.finish_polygon())
        self.root.bind("<Escape>", lambda _event: self.cancel_working_shape())
        self.root.bind("<Left>", lambda _event: self.previous_image())
        self.root.bind("<Right>", lambda _event: self.next_image())
        for index in range(1, 10):
            self.root.bind(str(index), lambda _event, value=index - 1: self.select_class(value))

    def choose_dataset(self) -> None:
        selected = filedialog.askopenfilename(
            title="選擇 YOLO data.yaml",
            filetypes=(("YOLO YAML", "*.yaml *.yml"), ("All files", "*.*")),
        )
        if selected:
            self.open_dataset(selected)

    def create_dataset(self) -> None:
        destination = filedialog.askdirectory(title="選擇新資料集資料夾")
        if not destination:
            return
        names_text = simpledialog.askstring(
            "零件類別",
            "輸入類別名稱，以逗號分隔：\n例如 GPIO, USB-C, CSI, HDMI",
            parent=self.root,
        )
        if not names_text:
            return
        names = [value.strip() for value in names_text.split(",") if value.strip()]
        segment = messagebox.askyesno(
            "標註格式",
            "使用 Segmentation 多邊形標註？\n選『否』會建立 Detection 方框資料集。",
        )
        try:
            data_yaml = create_component_dataset(
                destination, names, task="segment" if segment else "detect"
            )
        except Exception as exc:
            messagebox.showerror("建立失敗", str(exc))
            return
        self.open_dataset(str(data_yaml))

    def open_dataset(self, path: str) -> None:
        if self._work_in_progress():
            return
        if not self._leave_current_image():
            return
        try:
            self.dataset = ComponentLabelDataset(path)
        except Exception as exc:
            messagebox.showerror("資料集錯誤", str(exc))
            return
        self.data_var.set(str(self.dataset.data_yaml))
        self.class_list.delete(0, "end")
        for index, name in enumerate(self.dataset.class_names):
            self.class_list.insert("end", f"{index + 1}. {name}")
        if self.dataset.class_names:
            self.class_list.selection_set(0)
        available_splits = [
            split for split in ("train", "val", "test")
            if self.dataset.image_roots.get(split) is not None
        ]
        self.split_combo.configure(values=available_splits)
        if self.split_var.get() not in available_splits:
            self.split_var.set(available_splits[0] if available_splits else "train")
        self.change_split()
        self.status_var.set(
            f"Opened {self.dataset.task} dataset · {len(self.dataset.class_names)} classes"
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
        self.images = self.dataset.images(self.split_var.get())
        self.image_index = 0 if self.images else -1
        self.load_current_image()

    def current_class_id(self) -> int:
        selection = self.class_list.curselection()
        return int(selection[0]) if selection else 0

    def select_class(self, index: int) -> None:
        if self.dataset is None or not 0 <= index < len(self.dataset.class_names):
            return
        self.class_list.selection_clear(0, "end")
        self.class_list.selection_set(index)
        self.class_list.see(index)
        self.redraw()

    def load_current_image(self) -> None:
        self.cancel_working_shape()
        self.history.clear()
        self.redo_history.clear()
        self.selected_annotation = -1
        if self.dataset is None or not 0 <= self.image_index < len(self.images):
            self.current_image = None
            self.original_image = None
            self.annotations = []
            self.dirty = False
            self.redraw()
            self.update_status()
            return
        self.current_image = self.images[self.image_index]
        try:
            self.original_image = Image.open(self.current_image).convert("RGB")
            self.annotations = self.dataset.load(self.current_image, self.split_var.get())
        except Exception as exc:
            messagebox.showerror("圖片／標籤錯誤", str(exc))
            self.original_image = None
            self.annotations = []
        review_status = self.dataset.review.status(
            self.dataset.key(self.current_image, self.split_var.get())
        )
        if review_status == "auto_pending":
            for annotation in self.annotations:
                annotation.source = "auto"
        self.zoom = 1.0
        self.dirty = False
        self.refresh_annotation_list()
        self.redraw()
        self.update_status()

    def update_status(self) -> None:
        if self.dataset is None:
            self.image_status_var.set("尚未開啟資料集")
            self.progress_var.set("")
            return
        progress = self.dataset.progress(self.split_var.get())
        index = self.image_index + 1 if self.image_index >= 0 else 0
        review = (
            self.dataset.review.status(self.dataset.key(self.current_image, self.split_var.get()))
            if self.current_image is not None else "-"
        )
        self.image_status_var.set(
            f"{self.split_var.get()} · {index}/{len(self.images)} · {review}"
        )
        self.progress_var.set(
            f"總數 {progress['total']}\n已標 {progress['labeled']} · "
            f"人工確認 {progress['reviewed']} · 待確認 {progress['auto_pending']} · "
            f"未標 {progress['unlabeled']}"
        )

    def _leave_current_image(self) -> bool:
        if not self.dirty or self.current_image is None:
            return True
        if self.auto_save_var.get():
            return self.save_current("draft")
        decision = messagebox.askyesnocancel("尚未保存", "保存目前修改？")
        if decision is None:
            return False
        if decision:
            return self.save_current("draft")
        return True

    def save_current(self, status: str) -> bool:
        if self.dataset is None or self.current_image is None or self._work_in_progress():
            return False
        try:
            self.dataset.save(
                self.current_image,
                self.split_var.get(),
                self.annotations,
                status=status,
                annotation_count=len(self.annotations),
            )
        except Exception as exc:
            messagebox.showerror("保存失敗", str(exc))
            return False
        self.dirty = False
        self.status_var.set(f"Saved · {status} · {self.current_image.name}")
        self.update_status()
        return True

    def save_draft(self) -> None:
        self.save_current("draft")

    def confirm_and_next(self) -> None:
        if not self.save_current("negative" if not self.annotations else "reviewed"):
            return
        self.next_pending()

    def mark_negative(self) -> None:
        if self.current_image is None or self._work_in_progress():
            return
        if self.annotations and not messagebox.askyesno(
            "標記負樣本", "這會清除目前所有零件標註，確定繼續？"
        ):
            return
        self._record_history()
        self.annotations = []
        self.working_points = []
        self.dirty = True
        self.refresh_annotation_list()
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
            or not self.images
            or self.dataset is None
            or not self._leave_current_image()
        ):
            return
        for step in range(1, len(self.images) + 1):
            index = (self.image_index + step) % len(self.images)
            image = self.images[index]
            if predicate(image):
                self.image_index = index
                self.load_current_image()
                return
        self.status_var.set("No matching image")

    def next_unlabeled(self) -> None:
        if self.dataset is None:
            return
        split = self.split_var.get()
        self._find_next(lambda image: not self.dataset.label_path(image, split).is_file())

    def next_pending(self) -> None:
        if self.dataset is None:
            return
        split = self.split_var.get()
        self._find_next(
            lambda image: self.dataset.review.status(self.dataset.key(image, split)) == "auto_pending"
        )

    def _record_history(self) -> None:
        self.history.append(clone_annotations(self.annotations))
        if len(self.history) > 100:
            self.history.pop(0)
        self.redo_history.clear()

    def undo(self) -> None:
        if self._work_in_progress():
            return
        if self.working_points:
            self.working_points.pop()
            self.redraw()
            return
        if not self.history:
            return
        self.redo_history.append(clone_annotations(self.annotations))
        self.annotations = self.history.pop()
        self.dirty = True
        self.selected_annotation = -1
        self.refresh_annotation_list()
        self.redraw()

    def redo(self) -> None:
        if self._work_in_progress():
            return
        if not self.redo_history:
            return
        self.history.append(clone_annotations(self.annotations))
        self.annotations = self.redo_history.pop()
        self.dirty = True
        self.refresh_annotation_list()
        self.redraw()

    def delete_selected(self) -> None:
        if self._work_in_progress() or not 0 <= self.selected_annotation < len(self.annotations):
            return
        self._record_history()
        del self.annotations[self.selected_annotation]
        self.selected_annotation = -1
        self.dirty = True
        self.refresh_annotation_list()
        self.redraw()

    def clear_all(self) -> None:
        if self._work_in_progress() or not self.annotations:
            return
        if not messagebox.askyesno("清除標註", "清除目前圖片的所有標註？"):
            return
        self._record_history()
        self.annotations = []
        self.selected_annotation = -1
        self.dirty = True
        self.refresh_annotation_list()
        self.redraw()

    def cancel_working_shape(self) -> None:
        self.working_points = []
        self.drag_box_start = None
        self.drag_vertex = None
        self.redraw()

    def finish_polygon(self) -> None:
        if self._work_in_progress():
            return
        if len(self.working_points) < 3:
            self.status_var.set("Polygon needs at least 3 points")
            return
        self._record_history()
        self.annotations.append(
            Annotation(self.current_class_id(), list(self.working_points), source="manual")
        )
        self.working_points = []
        self.selected_annotation = len(self.annotations) - 1
        self.dirty = True
        self.refresh_annotation_list()
        self.redraw()

    def _mode_changed(self) -> None:
        self.cancel_working_shape()
        self.canvas.configure(cursor="fleur" if self.mode_var.get() == "edit" else "crosshair")
        self._save_settings()

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
        return self.offset_x + point[0] * width * scale, self.offset_y + point[1] * height * scale

    def canvas_press(self, event) -> None:
        if self._work_in_progress():
            return
        point = self._canvas_to_normalized(event.x, event.y)
        if point is None or self.current_image is None:
            return
        mode = self.mode_var.get()
        if mode == "polygon":
            self.working_points.append(point)
            self.redraw()
        elif mode == "box":
            self.drag_box_start = point
        elif mode == "edit":
            found = self._nearest_vertex(event.x, event.y)
            if found is not None:
                self._record_history()
                self.drag_vertex = found
                self.selected_annotation = found[0]
                self.refresh_annotation_list()
            else:
                self._select_annotation_at(event.x, event.y)

    def canvas_drag(self, event) -> None:
        if self._work_in_progress():
            return
        point = self._canvas_to_normalized(event.x, event.y)
        if point is None:
            return
        if self.mode_var.get() == "edit" and self.drag_vertex is not None:
            annotation_index, vertex_index = self.drag_vertex
            self.annotations[annotation_index].points[vertex_index] = point
            self.dirty = True
            self.redraw()
        elif self.mode_var.get() == "box" and self.drag_box_start is not None:
            self.working_points = [self.drag_box_start, point]
            self.redraw()

    def canvas_release(self, event) -> None:
        if self._work_in_progress():
            return
        point = self._canvas_to_normalized(event.x, event.y)
        if self.mode_var.get() == "edit":
            self.drag_vertex = None
            self.refresh_annotation_list()
            return
        if self.mode_var.get() != "box" or self.drag_box_start is None or point is None:
            return
        x1, y1 = self.drag_box_start
        x2, y2 = point
        self.drag_box_start = None
        self.working_points = []
        if abs(x2 - x1) < 0.005 or abs(y2 - y1) < 0.005:
            self.redraw()
            return
        self._record_history()
        points = [
            (min(x1, x2), min(y1, y2)),
            (max(x1, x2), min(y1, y2)),
            (max(x1, x2), max(y1, y2)),
            (min(x1, x2), max(y1, y2)),
        ]
        self.annotations.append(Annotation(self.current_class_id(), points, source="manual"))
        self.selected_annotation = len(self.annotations) - 1
        self.dirty = True
        self.refresh_annotation_list()
        self.redraw()

    def canvas_right_click(self, _event) -> None:
        if self._work_in_progress():
            return
        if self.working_points:
            self.working_points.pop()
            self.redraw()

    def canvas_wheel(self, event) -> None:
        self.zoom = min(4.0, max(0.5, self.zoom * (1.12 if event.delta > 0 else 1 / 1.12)))
        self.redraw()

    def _nearest_vertex(self, x: float, y: float) -> tuple[int, int] | None:
        best = None
        best_distance = 14.0
        for annotation_index, annotation in enumerate(self.annotations):
            for vertex_index, point in enumerate(annotation.points):
                px, py = self._normalized_to_canvas(point)
                distance = float(np.hypot(px - x, py - y))
                if distance < best_distance:
                    best_distance = distance
                    best = (annotation_index, vertex_index)
        return best

    def _select_annotation_at(self, x: float, y: float) -> None:
        for index in range(len(self.annotations) - 1, -1, -1):
            polygon = np.asarray(
                [self._normalized_to_canvas(point) for point in self.annotations[index].points],
                dtype=np.float32,
            )
            if cv2.pointPolygonTest(polygon, (float(x), float(y)), False) >= 0:
                self.selected_annotation = index
                self.refresh_annotation_list()
                self.redraw()
                return

    def annotation_selected(self, _event) -> None:
        selection = self.annotation_list.curselection()
        self.selected_annotation = int(selection[0]) if selection else -1
        self.redraw()

    def refresh_annotation_list(self) -> None:
        self.annotation_list.delete(0, "end")
        if self.dataset is None:
            return
        for index, annotation in enumerate(self.annotations):
            name = self.dataset.class_names[annotation.class_id]
            confidence = (
                f" · {annotation.confidence:.0%}" if annotation.confidence is not None else ""
            )
            self.annotation_list.insert(
                "end", f"{index + 1}. {name} · {len(annotation.points)} pts{confidence}"
            )
        if 0 <= self.selected_annotation < len(self.annotations):
            self.annotation_list.selection_set(self.selected_annotation)
            self.annotation_list.see(self.selected_annotation)

    def redraw(self) -> None:
        if not hasattr(self, "canvas"):
            return
        self.canvas.delete("all")
        if self.original_image is None:
            self.canvas.create_text(
                max(self.canvas.winfo_width() / 2, 300),
                max(self.canvas.winfo_height() / 2, 200),
                text="開啟資料集並匯入圖片\nOpen a dataset and import images",
                fill="#9aa7b8",
                font=("Microsoft JhengHei UI", 16),
                justify="center",
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
        displayed = self.original_image.resize((display_width, display_height), Image.Resampling.LANCZOS)
        self.photo_image = ImageTk.PhotoImage(displayed)
        self.canvas.create_image(self.offset_x, self.offset_y, image=self.photo_image, anchor="nw")
        if self.dataset is None:
            return
        for index, annotation in enumerate(self.annotations):
            color = PALETTE[annotation.class_id % len(PALETTE)]
            coords = [value for point in annotation.points for value in self._normalized_to_canvas(point)]
            width = 4 if index == self.selected_annotation else 2
            self.canvas.create_polygon(
                coords,
                outline=color,
                fill=color,
                stipple="gray25",
                width=width,
            )
            first_x, first_y = self._normalized_to_canvas(annotation.points[0])
            label = self.dataset.class_names[annotation.class_id]
            if annotation.confidence is not None:
                label += f" {annotation.confidence:.0%}"
            self.canvas.create_text(
                first_x + 4,
                first_y - 6,
                text=label,
                fill="#ffffff",
                anchor="sw",
                font=("Microsoft JhengHei UI", 10, "bold"),
            )
            if self.mode_var.get() == "edit" and index == self.selected_annotation:
                for point in annotation.points:
                    x, y = self._normalized_to_canvas(point)
                    self.canvas.create_oval(x - 5, y - 5, x + 5, y + 5, fill="#ffffff", outline=color, width=2)
        if self.working_points:
            if self.mode_var.get() == "box" and len(self.working_points) == 2:
                p1 = self._normalized_to_canvas(self.working_points[0])
                p2 = self._normalized_to_canvas(self.working_points[1])
                self.canvas.create_rectangle(*p1, *p2, outline="#ffffff", dash=(5, 3), width=2)
            else:
                coords = [value for point in self.working_points for value in self._normalized_to_canvas(point)]
                if len(coords) >= 4:
                    self.canvas.create_line(*coords, fill="#ffffff", dash=(5, 3), width=2)
                for point in self.working_points:
                    x, y = self._normalized_to_canvas(point)
                    self.canvas.create_oval(x - 4, y - 4, x + 4, y + 4, fill="#ffffff")

    def choose_prelabel_model(self) -> None:
        selected = filedialog.askopenfilename(
            title="選擇自動預標模型",
            filetypes=(("YOLO model", "*.pt *.onnx"), ("All files", "*.*")),
        )
        if selected:
            self.model_var.set(selected)
            self.prelabel_model = None
            self.prelabel_model_loaded_path = ""
            self._save_settings()

    def _confidence(self) -> float:
        value = float(self.confidence_var.get())
        if not 0.01 <= value <= 0.99:
            raise ValueError("confidence must be between 0.01 and 0.99")
        return value

    def _model_path(self) -> str:
        return str(Path(self.model_var.get()).expanduser().resolve())

    def _load_prelabel_model(self, path: str):
        if not Path(path).is_file():
            raise FileNotFoundError(f"pre-label model not found: {path}")
        if self.prelabel_model is None or self.prelabel_model_loaded_path != path:
            from ultralytics import YOLO

            self.prelabel_model = YOLO(path)
            self.prelabel_model_loaded_path = path
        return self.prelabel_model

    def _predict_image(
        self,
        image: Path,
        *,
        model_path: str,
        confidence: float,
    ) -> tuple[list[Annotation], list[str]]:
        if self.dataset is None:
            return [], []
        model = self._load_prelabel_model(model_path)
        result = model.predict(
            source=str(image),
            conf=confidence,
            verbose=False,
        )[0]
        return annotations_from_ultralytics_result(
            result,
            self.dataset.class_names,
            task=self.dataset.task,
        )

    def prelabel_current(self) -> None:
        if self.dataset is None or self.current_image is None or self._work_in_progress():
            return
        if self.annotations and not messagebox.askyesno(
            "取代目前標註？",
            "自動預標會取代畫面中尚未保存的標註；原 label 仍有 session 備份。",
        ):
            return
        try:
            model_path = self._model_path()
            confidence = self._confidence()
        except Exception as exc:
            messagebox.showerror("自動預標設定錯誤", str(exc))
            return
        image = self.current_image
        self.single_prelabel_running = True
        self.prelabel_button.configure(state="disabled")
        self.batch_button.configure(state="disabled")
        self.status_var.set("Auto-labeling current image…")

        def worker() -> None:
            try:
                annotations, skipped = self._predict_image(
                    image,
                    model_path=model_path,
                    confidence=confidence,
                )
                error = None
            except Exception as exc:
                annotations, skipped, error = [], [], str(exc)
            self._post_to_ui(
                lambda: self._apply_current_prelabel(
                    image,
                    annotations,
                    skipped,
                    error,
                    model_path,
                    confidence,
                )
            )

        threading.Thread(target=worker, daemon=True).start()

    def _apply_current_prelabel(
        self,
        image: Path,
        annotations: list[Annotation],
        skipped: list[str],
        error: str | None,
        model_path: str,
        confidence: float,
    ) -> None:
        self.single_prelabel_running = False
        self.prelabel_button.configure(state="normal")
        self.batch_button.configure(state="normal")
        if error:
            messagebox.showerror("自動預標失敗", error)
            self.status_var.set("Auto-label failed")
            return
        if image != self.current_image:
            return
        if not annotations:
            self.status_var.set("Auto-label completed · no object detected; original label kept")
            return
        self._record_history()
        self.annotations = annotations
        self.selected_annotation = 0 if annotations else -1
        self.dirty = True
        self.refresh_annotation_list()
        self.redraw()
        try:
            assert self.dataset is not None
            self.dataset.save(
                image,
                self.split_var.get(),
                annotations,
                status="auto_pending",
                model=model_path,
                confidence_threshold=confidence,
                skipped_model_classes=skipped,
            )
        except Exception as exc:
            messagebox.showerror("自動預標保存失敗", str(exc))
            self.status_var.set("Auto-label save failed")
            return
        self.dirty = False
        self.status_var.set(
            f"Auto-labeled {len(annotations)} objects" + (f" · skipped {skipped}" if skipped else "")
        )
        self.update_status()

    def batch_prelabel(self) -> None:
        if self.dataset is None or self._work_in_progress():
            return
        if not self._leave_current_image():
            return
        split = self.split_var.get()
        targets = [
            image for image in self.images
            if not self.dataset.label_path(image, split).is_file()
        ]
        if not targets:
            messagebox.showinfo("沒有未標圖片", "目前 split 的圖片都已有 label。")
            return
        if not messagebox.askyesno(
            "批次自動預標",
            f"將處理 {len(targets)} 張未標圖片。\n既有 label 不會被覆蓋，繼續？",
        ):
            return
        try:
            model_path = self._model_path()
            confidence = self._confidence()
        except Exception as exc:
            messagebox.showerror("自動預標設定錯誤", str(exc))
            return
        self.batch_running = True
        self.batch_cancel.clear()
        self.batch_button.configure(state="disabled")
        self.prelabel_button.configure(state="disabled")
        self.cancel_batch_button.configure(state="normal")
        self.status_var.set(f"Batch auto-label 0/{len(targets)}")

        def worker() -> None:
            saved = empty = failed = 0
            try:
                self._load_prelabel_model(model_path)
                for index, image in enumerate(targets, 1):
                    if self.batch_cancel.is_set():
                        break
                    try:
                        annotations, skipped = self._predict_image(
                            image,
                            model_path=model_path,
                            confidence=confidence,
                        )
                        if annotations:
                            assert self.dataset is not None
                            self.dataset.save(
                                image,
                                split,
                                annotations,
                                status="auto_pending",
                                model=model_path,
                                confidence_threshold=confidence,
                                skipped_model_classes=skipped,
                            )
                            saved += 1
                        else:
                            empty += 1
                    except Exception:
                        failed += 1
                    self._post_to_ui(
                        lambda current=index, total=len(targets), count=saved: self.status_var.set(
                            f"Batch auto-label {current}/{total} · saved {count}"
                        ),
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
        self.status_var.set("Stopping batch…")

    def _batch_finished(self, saved: int, empty: int, failed: int) -> None:
        self.batch_running = False
        self.batch_button.configure(state="normal")
        self.prelabel_button.configure(state="normal")
        self.cancel_batch_button.configure(state="disabled")
        self.status_var.set(f"Batch done · saved {saved} · no detection {empty} · failed {failed}")
        if not self.dirty:
            self.load_current_image()
        self.update_status()

    def _current_image_root(self) -> Path | None:
        if self.dataset is None:
            return None
        return self.dataset.image_roots.get(self.split_var.get())

    def import_image_folder(self) -> None:
        if self._work_in_progress():
            return
        destination = self._current_image_root()
        if destination is None:
            messagebox.showwarning("尚未開啟資料集", "請先開啟或建立資料集。")
            return
        folder = filedialog.askdirectory(title="選擇要匯入的圖片資料夾")
        if not folder:
            return
        sources = [
            path for path in Path(folder).rglob("*")
            if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
        ]
        if not sources:
            messagebox.showinfo("沒有圖片", "選擇的資料夾沒有支援的圖片。")
            return
        if not messagebox.askyesno(
            "匯入圖片",
            f"複製 {len(sources)} 張圖片到 {self.split_var.get()} split？",
        ):
            return
        copied = import_images(sources, destination)
        self.images = self.dataset.images(self.split_var.get())
        self.status_var.set(f"Imported {len(copied)} images")
        self.update_status()
        if self.image_index < 0 and self.images:
            self.image_index = 0
            self.load_current_image()

    def import_video(self) -> None:
        if self._work_in_progress():
            return
        destination = self._current_image_root()
        if destination is None:
            messagebox.showwarning("尚未開啟資料集", "請先開啟或建立資料集。")
            return
        video = filedialog.askopenfilename(
            title="選擇影片",
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
        self.status_var.set("Extracting video frames…")

        def worker() -> None:
            try:
                saved = extract_video_frames(
                    video, destination, interval_s=interval, max_frames=maximum
                )
                error = None
            except Exception as exc:
                saved, error = [], str(exc)
            self.root.after(0, lambda: self._video_finished(saved, error))

        threading.Thread(target=worker, daemon=True).start()

    def _video_finished(self, saved: list[Path], error: str | None) -> None:
        if error:
            messagebox.showerror("影片取幀失敗", error)
            self.status_var.set("Video extraction failed")
            return
        if self.dataset is not None:
            self.images = self.dataset.images(self.split_var.get())
        self.status_var.set(f"Extracted {len(saved)} frames")
        self.update_status()
        messagebox.showinfo("影片取幀完成", f"已加入 {len(saved)} 張未標圖片。")

    def _save_settings(self) -> None:
        payload = {
            "data": self.data_var.get(),
            "split": self.split_var.get(),
            "mode": self.mode_var.get(),
            "auto_save": self.auto_save_var.get(),
            "model": self.model_var.get(),
            "confidence": self.confidence_var.get(),
        }
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_PATH.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    def close(self) -> None:
        if self.batch_running:
            if not messagebox.askyesno("批次預標進行中", "停止批次並關閉？"):
                return
            self.batch_cancel.set()
        if self.single_prelabel_running and not messagebox.askyesno(
            "自動預標進行中", "目前圖片仍在推論，確定關閉？"
        ):
            return
        if not self._leave_current_image():
            return
        self.closing = True
        self._save_settings()
        self.root.destroy()

    def _work_in_progress(self) -> bool:
        if self.batch_running:
            self.status_var.set("批次預標進行中；可先按「停止批次」。")
            return True
        if self.single_prelabel_running:
            self.status_var.set("目前圖片正在自動預標，請稍候。")
            return True
        return False

    def _post_to_ui(self, callback) -> None:
        if self.closing:
            return
        try:
            self.root.after(0, callback)
        except tk.TclError:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default="")
    args = parser.parse_args()
    root = tk.Tk()
    ComponentLabelStudio(root, args.data)
    root.mainloop()


if __name__ == "__main__":
    main()
