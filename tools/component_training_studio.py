# -*- coding: utf-8 -*-
"""Windows GUI for reusable Board Vision component-model training."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import webbrowser

from component_dataset import audit_component_dataset, format_audit_report
from component_model_package import install_runtime_package


ROOT = Path(__file__).resolve().parent.parent
SETTINGS_PATH = ROOT / "training" / "component-studio.json"
RUNTIME_MODEL = ROOT / "models" / "pi5-components-seg.onnx"


def _default_dataset() -> str:
    candidates = [
        Path.home() / "Downloads" / "pi5_data" / "data.yaml",
        ROOT / "training" / "components.yaml",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return ""


def _load_settings() -> dict:
    if not SETTINGS_PATH.is_file():
        return {}
    try:
        payload = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


class ComponentTrainingStudio:
    def __init__(self, root: tk.Tk, initial_data: str = "") -> None:
        self.root = root
        self.root.title("Board Vision - 零件辨識訓練中心 / Component Training Studio")
        self.root.geometry("1180x820")
        self.root.minsize(980, 700)
        self.process: subprocess.Popen[str] | None = None
        self.audit_report: dict | None = None
        settings = _load_settings()

        self.data_var = tk.StringVar(value=initial_data or settings.get("data") or _default_dataset())
        self.task_var = tk.StringVar(value=settings.get("task", "auto"))
        self.model_var = tk.StringVar(
            value=settings.get("model", str(ROOT / "yolo11n-seg.pt"))
        )
        self.output_var = tk.StringVar(
            value=settings.get(
                "output", str(ROOT / "models" / "component-studio" / "components-seg-custom.onnx")
            )
        )
        self.run_name_var = tk.StringVar(value=settings.get("run_name", "components-seg-custom"))
        self.epochs_var = tk.StringVar(value=str(settings.get("epochs", 120)))
        self.imgsz_var = tk.StringVar(value=str(settings.get("imgsz", 640)))
        self.batch_var = tk.StringVar(value=str(settings.get("batch", 16)))
        self.device_var = tk.StringVar(value=settings.get("device", "0"))
        self.workers_var = tk.StringVar(value=str(settings.get("workers", 4)))
        self.augmentation_var = tk.StringVar(
            value=settings.get("augmentation", "occlusion-robust")
        )
        self.overwrite_var = tk.BooleanVar(value=bool(settings.get("overwrite", False)))
        self.license_var = tk.BooleanVar(value=bool(settings.get("license", True)))
        self.summary_var = tk.StringVar(value="尚未檢查資料集 / Dataset not audited")
        self.status_var = tk.StringVar(value="Ready")

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        if self.data_var.get():
            self.root.after(450, self.audit_dataset)

    def _build_ui(self) -> None:
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("Title.TLabel", font=("Microsoft JhengHei UI", 18, "bold"))
        style.configure("Header.TLabel", font=("Microsoft JhengHei UI", 10, "bold"))
        style.configure("Accent.TButton", font=("Microsoft JhengHei UI", 10, "bold"))

        container = ttk.Frame(self.root, padding=16)
        container.pack(fill="both", expand=True)
        ttk.Label(
            container,
            text="零件辨識訓練中心  Component Training Studio",
            style="Title.TLabel",
        ).pack(anchor="w")
        ttk.Label(
            container,
            text="資料檢查 → YOLO11 訓練 → Test 評估 → ONNX＋類別檔 → 安裝到 Board Vision",
        ).pack(anchor="w", pady=(2, 12))

        dataset_box = ttk.LabelFrame(container, text="1. 資料集 Dataset", padding=10)
        dataset_box.pack(fill="x")
        dataset_box.columnconfigure(1, weight=1)
        ttk.Label(dataset_box, text="data.yaml").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(dataset_box, textvariable=self.data_var).grid(row=0, column=1, sticky="ew")
        ttk.Button(dataset_box, text="選擇…", command=self.choose_dataset).grid(row=0, column=2, padx=(8, 0))
        ttk.Button(dataset_box, text="開啟資料夾", command=self.open_dataset_folder).grid(
            row=0, column=3, padx=(8, 0)
        )
        ttk.Label(dataset_box, textvariable=self.summary_var, style="Header.TLabel").grid(
            row=1, column=0, columnspan=4, sticky="w", pady=(10, 0)
        )

        settings_box = ttk.LabelFrame(container, text="2. 訓練設定 Training", padding=10)
        settings_box.pack(fill="x", pady=(12, 0))
        for column in (1, 3, 5):
            settings_box.columnconfigure(column, weight=1)
        fields = [
            ("Task", self.task_var, ("auto", "segment", "detect")),
            ("Augmentation", self.augmentation_var, ("occlusion-robust", "small-parts", "standard")),
            ("Device", self.device_var, ("0", "cpu")),
        ]
        for index, (label, variable, values) in enumerate(fields):
            column = index * 2
            ttk.Label(settings_box, text=label).grid(row=0, column=column, sticky="w", padx=(0, 6))
            ttk.Combobox(
                settings_box, textvariable=variable, values=values, state="readonly", width=18
            ).grid(row=0, column=column + 1, sticky="ew", padx=(0, 14))

        numeric_fields = [
            ("Epochs", self.epochs_var),
            ("Image size", self.imgsz_var),
            ("Batch", self.batch_var),
            ("Workers", self.workers_var),
        ]
        for index, (label, variable) in enumerate(numeric_fields):
            column = index * 2
            ttk.Label(settings_box, text=label).grid(row=1, column=column, sticky="w", pady=(9, 0), padx=(0, 6))
            ttk.Entry(settings_box, textvariable=variable, width=10).grid(
                row=1, column=column + 1, sticky="ew", pady=(9, 0), padx=(0, 14)
            )

        ttk.Label(settings_box, text="Base model").grid(row=2, column=0, sticky="w", pady=(9, 0))
        ttk.Entry(settings_box, textvariable=self.model_var).grid(
            row=2, column=1, columnspan=4, sticky="ew", pady=(9, 0), padx=(6, 6)
        )
        ttk.Button(settings_box, text="選擇…", command=self.choose_model).grid(row=2, column=5, pady=(9, 0))
        ttk.Label(settings_box, text="Output ONNX").grid(row=3, column=0, sticky="w", pady=(9, 0))
        ttk.Entry(settings_box, textvariable=self.output_var).grid(
            row=3, column=1, columnspan=4, sticky="ew", pady=(9, 0), padx=(6, 6)
        )
        ttk.Button(settings_box, text="選擇…", command=self.choose_output).grid(row=3, column=5, pady=(9, 0))
        ttk.Label(settings_box, text="Run name").grid(row=4, column=0, sticky="w", pady=(9, 0))
        ttk.Entry(settings_box, textvariable=self.run_name_var).grid(
            row=4, column=1, columnspan=2, sticky="ew", pady=(9, 0), padx=(6, 14)
        )
        ttk.Checkbutton(settings_box, text="允許覆蓋（會先備份）", variable=self.overwrite_var).grid(
            row=4, column=3, columnspan=2, sticky="w", pady=(9, 0)
        )
        ttk.Checkbutton(
            settings_box,
            text="已確認 Ultralytics AGPL-3.0／Enterprise 授權",
            variable=self.license_var,
        ).grid(row=5, column=0, columnspan=6, sticky="w", pady=(9, 0))

        actions = ttk.Frame(container)
        actions.pack(fill="x", pady=(12, 8))
        self.audit_button = ttk.Button(actions, text="① 檢查資料", command=self.audit_dataset)
        self.audit_button.pack(side="left")
        self.train_button = ttk.Button(
            actions, text="② 開始訓練", command=self.start_training, style="Accent.TButton"
        )
        self.train_button.pack(side="left", padx=(8, 0))
        self.stop_button = ttk.Button(actions, text="停止", command=self.stop_training, state="disabled")
        self.stop_button.pack(side="left", padx=(8, 0))
        ttk.Separator(actions, orient="vertical").pack(side="left", fill="y", padx=12)
        self.install_button = ttk.Button(
            actions, text="③ 安裝到 Board Vision", command=self.install_model
        )
        self.install_button.pack(side="left")
        ttk.Button(actions, text="開啟輸出", command=self.open_output_folder).pack(side="left", padx=(8, 0))
        ttk.Button(
            actions, text="開啟 Board Vision", command=lambda: webbrowser.open("http://127.0.0.1:8100/")
        ).pack(side="right")

        self.progress = ttk.Progressbar(container, mode="indeterminate")
        self.progress.pack(fill="x")
        log_box = ttk.LabelFrame(container, text="執行紀錄 Log", padding=6)
        log_box.pack(fill="both", expand=True, pady=(8, 0))
        self.log = tk.Text(
            log_box,
            wrap="word",
            font=("Cascadia Mono", 9),
            background="#10151d",
            foreground="#dce7f5",
            insertbackground="#ffffff",
        )
        scrollbar = ttk.Scrollbar(log_box, command=self.log.yview)
        self.log.configure(yscrollcommand=scrollbar.set)
        self.log.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        ttk.Label(container, textvariable=self.status_var).pack(anchor="w", pady=(6, 0))

    def _append_log(self, text: str) -> None:
        self.log.insert("end", text.rstrip() + "\n")
        self.log.see("end")

    def choose_dataset(self) -> None:
        selected = filedialog.askopenfilename(
            title="選擇 YOLO data.yaml",
            filetypes=(("YOLO YAML", "*.yaml *.yml"), ("All files", "*.*")),
        )
        if selected:
            self.data_var.set(selected)
            self.audit_dataset()

    def choose_model(self) -> None:
        selected = filedialog.askopenfilename(
            title="選擇 YOLO base model",
            filetypes=(("PyTorch model", "*.pt"), ("All files", "*.*")),
        )
        if selected:
            self.model_var.set(selected)

    def choose_output(self) -> None:
        selected = filedialog.asksaveasfilename(
            title="選擇 ONNX 輸出位置",
            defaultextension=".onnx",
            filetypes=(("ONNX model", "*.onnx"),),
        )
        if selected:
            self.output_var.set(selected)

    def open_dataset_folder(self) -> None:
        path = Path(self.data_var.get()).expanduser()
        target = path.parent if path.is_file() else path
        if target.is_dir():
            os.startfile(str(target))
        else:
            messagebox.showerror("找不到資料集", str(target))

    def open_output_folder(self) -> None:
        target = Path(self.output_var.get()).expanduser().resolve().parent
        target.mkdir(parents=True, exist_ok=True)
        os.startfile(str(target))

    def audit_dataset(self) -> None:
        if self.process is not None:
            return
        data = self.data_var.get().strip()
        if not data:
            messagebox.showwarning("尚未選擇", "請先選擇 data.yaml")
            return
        self.audit_button.configure(state="disabled")
        self.status_var.set("正在檢查資料集…")
        self.progress.start(12)

        def worker() -> None:
            try:
                report = audit_component_dataset(data)
                error = None
            except Exception as exc:
                report = None
                error = str(exc)
            self.root.after(0, lambda: self._audit_finished(report, error))

        threading.Thread(target=worker, daemon=True).start()

    def _audit_finished(self, report: dict | None, error: str | None) -> None:
        self.progress.stop()
        self.audit_button.configure(state="normal")
        if error or report is None:
            self.audit_report = None
            self.summary_var.set("資料集無法讀取 / Dataset error")
            self.status_var.set("Audit failed")
            self._append_log("[AUDIT ERROR] " + (error or "unknown"))
            return
        self.audit_report = report
        train = report["splits"]["train"]["images"]
        val = report["splits"]["val"]["images"]
        test = report["splits"]["test"]["images"]
        self.summary_var.set(
            f"{report['status'].upper()} · {report['task']} · "
            f"{report['class_count']} classes · train {train} / val {val} / test {test}"
        )
        self.status_var.set("Dataset ready" if report["ready_to_train"] else "Dataset needs fixes")
        self._append_log("\n[AUDIT]\n" + format_audit_report(report))

    def _numeric_settings(self) -> tuple[int, int, int, int]:
        values = (
            int(self.epochs_var.get()),
            int(self.imgsz_var.get()),
            int(self.batch_var.get()),
            int(self.workers_var.get()),
        )
        if values[0] <= 0 or values[1] < 320 or values[2] <= 0 or values[3] < 0:
            raise ValueError("Epochs/Batch > 0, Image size >= 320, Workers >= 0")
        return values

    def start_training(self) -> None:
        if self.process is not None:
            return
        try:
            epochs, imgsz, batch, workers = self._numeric_settings()
            report = audit_component_dataset(self.data_var.get().strip())
        except Exception as exc:
            messagebox.showerror("無法開始", str(exc))
            return
        if not report["ready_to_train"]:
            self._audit_finished(report, None)
            messagebox.showerror("資料未通過", "請先修正 Audit 列出的錯誤。")
            return
        if not self.license_var.get():
            messagebox.showwarning("授權確認", "請先確認 Ultralytics 授權選項。")
            return
        output = Path(self.output_var.get()).expanduser().resolve()
        if output.exists() and not self.overwrite_var.get():
            messagebox.showwarning("輸出已存在", "勾選允許覆蓋，或選擇新的輸出檔名。")
            return
        command = [
            sys.executable,
            str(ROOT / "tools" / "train_yolo_components.py"),
            "--data", self.data_var.get().strip(),
            "--task", self.task_var.get(),
            "--model", self.model_var.get().strip(),
            "--output", str(output),
            "--epochs", str(epochs),
            "--imgsz", str(imgsz),
            "--batch", str(batch),
            "--workers", str(workers),
            "--device", self.device_var.get().strip(),
            "--project", str(ROOT / "runs" / "components"),
            "--name", self.run_name_var.get().strip() or "component-model",
            "--augmentation", self.augmentation_var.get(),
            "--accept-ultralytics-license",
        ]
        if self.overwrite_var.get():
            command.append("--overwrite")
        self._save_settings()
        self._append_log("\n[TRAIN] starting: " + " ".join(command[1:]))
        environment = os.environ.copy()
        environment["PYTHONUNBUFFERED"] = "1"
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            self.process = subprocess.Popen(
                command,
                cwd=str(ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                creationflags=creationflags,
            )
        except OSError as exc:
            self.process = None
            messagebox.showerror("啟動失敗", str(exc))
            return
        self.train_button.configure(state="disabled")
        self.audit_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.progress.start(10)
        self.status_var.set("Training…")
        threading.Thread(target=self._read_training_output, daemon=True).start()

    def _read_training_output(self) -> None:
        process = self.process
        assert process is not None and process.stdout is not None
        for line in process.stdout:
            self.root.after(0, lambda value=line: self._append_log(value))
        return_code = process.wait()
        self.root.after(0, lambda: self._training_finished(return_code))

    def _training_finished(self, return_code: int) -> None:
        self.process = None
        self.progress.stop()
        self.train_button.configure(state="normal")
        self.audit_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        if return_code == 0:
            self.status_var.set("Training complete · ONNX ready")
            self._append_log("[DONE] Training, evaluation, and ONNX export completed.")
            messagebox.showinfo("訓練完成", "模型與類別 manifest 已輸出，可按『安裝到 Board Vision』。")
        else:
            self.status_var.set(f"Training failed (exit {return_code})")
            self._append_log(f"[FAILED] process exit code={return_code}")

    def stop_training(self) -> None:
        if self.process is None:
            return
        if messagebox.askyesno("停止訓練", "確定要停止目前訓練？已完成的 run 檔案會保留。"):
            self.process.terminate()
            self.status_var.set("Stopping…")

    def install_model(self) -> None:
        if self.process is not None:
            messagebox.showwarning("仍在訓練", "請等待訓練結束。")
            return
        try:
            result = install_runtime_package(self.output_var.get(), RUNTIME_MODEL)
        except Exception as exc:
            messagebox.showerror("安裝失敗", str(exc))
            return
        self._append_log("\n[INSTALL]\n" + json.dumps(result, ensure_ascii=False, indent=2))
        self.status_var.set("Installed · restart Board Vision to load the model")
        messagebox.showinfo(
            "安裝完成",
            "模型與類別名稱已安裝；舊模型已備份。重新啟動 Board Vision 後生效。\n\n"
            "此動作不會自動打開 Segmentation UI。",
        )

    def _save_settings(self) -> None:
        payload = {
            "data": self.data_var.get(),
            "task": self.task_var.get(),
            "model": self.model_var.get(),
            "output": self.output_var.get(),
            "run_name": self.run_name_var.get(),
            "epochs": self.epochs_var.get(),
            "imgsz": self.imgsz_var.get(),
            "batch": self.batch_var.get(),
            "device": self.device_var.get(),
            "workers": self.workers_var.get(),
            "augmentation": self.augmentation_var.get(),
            "overwrite": self.overwrite_var.get(),
            "license": self.license_var.get(),
        }
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_PATH.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    def close(self) -> None:
        if self.process is not None and not messagebox.askyesno(
            "訓練進行中", "關閉視窗會停止目前訓練，確定繼續？"
        ):
            return
        if self.process is not None:
            self.process.terminate()
        self._save_settings()
        self.root.destroy()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default="")
    args = parser.parse_args()
    root = tk.Tk()
    ComponentTrainingStudio(root, args.data)
    root.mainloop()


if __name__ == "__main__":
    main()

