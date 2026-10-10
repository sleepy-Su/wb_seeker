from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
import webbrowser
from datetime import date, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .errors import OperationCancelled, WeiboDownloaderError
from .paths import application_dir, default_cookie_path, default_download_dir
from .service import DownloadRequest, DownloadRunResult, run_download


class DownloaderApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("微博博主正文原图下载器")
        self.root.geometry("900x640")
        self.root.minsize(780, 560)

        self.messages: queue.Queue[tuple[str, object]] = queue.Queue()
        self.cancel_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.closing = False

        self.profile_var = tk.StringVar()
        self.start_date_var = tk.StringVar(value=(date.today() - timedelta(days=7)).isoformat())
        self.end_date_var = tk.StringVar(value=date.today().isoformat())
        self.cookie_var = tk.StringVar(
            value=str(default_cookie_path()) if default_cookie_path().is_file() else ""
        )
        self.output_var = tk.StringVar(value=str(default_download_dir()))
        self.status_var = tk.StringVar(value="就绪")

        self.input_widgets: list[tk.Widget] = []
        self._build_styles()
        self._build_layout()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(100, self._drain_messages)
        self.profile_entry.focus_set()

    def _build_styles(self) -> None:
        style = ttk.Style(self.root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 16, "bold"))
        style.configure("Status.TLabel", foreground="#4b5563")
        style.configure("Accent.TButton", font=("Microsoft YaHei UI", 10, "bold"))

    def _build_layout(self) -> None:
        container = ttk.Frame(self.root, padding=18)
        container.grid(row=0, column=0, sticky="nsew")
        self.root.rowconfigure(0, weight=1)
        self.root.columnconfigure(0, weight=1)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(3, weight=1)

        ttk.Label(container, text="微博博主正文原图下载器", style="Title.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 14)
        )

        form = ttk.LabelFrame(container, text="抓取设置", padding=14)
        form.grid(row=1, column=0, sticky="ew")
        form.columnconfigure(1, weight=1)
        form.columnconfigure(3, minsize=108)

        ttk.Label(form, text="博主主页或 UID").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.profile_entry = ttk.Entry(form, textvariable=self.profile_var)
        self.profile_entry.grid(row=0, column=1, columnspan=3, sticky="ew", pady=4)

        ttk.Label(form, text="开始日期").grid(row=1, column=0, sticky="w", padx=(0, 8))
        start_entry = ttk.Entry(form, textvariable=self.start_date_var, width=16)
        start_entry.grid(row=1, column=1, sticky="ew", padx=(0, 16), pady=4)
        ttk.Label(form, text="结束日期").grid(row=1, column=2, sticky="w", padx=(0, 8))
        end_entry = ttk.Entry(form, textvariable=self.end_date_var, width=16)
        end_entry.grid(row=1, column=3, sticky="ew", pady=4)

        ttk.Label(form, text="Cookie 文件").grid(row=2, column=0, sticky="w", padx=(0, 8))
        cookie_entry = ttk.Entry(form, textvariable=self.cookie_var)
        cookie_entry.grid(row=2, column=1, columnspan=2, sticky="ew", padx=(0, 8), pady=4)
        self.cookie_button = ttk.Button(
            form, text="选择文件", width=10, command=self._choose_cookie
        )
        self.cookie_button.grid(row=2, column=3, sticky="ew", pady=4)

        ttk.Label(form, text="下载目录").grid(row=3, column=0, sticky="w", padx=(0, 8))
        output_entry = ttk.Entry(form, textvariable=self.output_var)
        output_entry.grid(row=3, column=1, columnspan=2, sticky="ew", padx=(0, 8), pady=4)
        self.output_button = ttk.Button(
            form, text="选择目录", width=10, command=self._choose_output
        )
        self.output_button.grid(row=3, column=3, sticky="ew", pady=4)

        self.input_widgets.extend(
            [
                self.profile_entry,
                start_entry,
                end_entry,
                cookie_entry,
                output_entry,
                self.cookie_button,
                self.output_button,
            ]
        )

        actions = ttk.Frame(container)
        actions.grid(row=2, column=0, sticky="ew", pady=14)
        actions.columnconfigure(3, weight=1)
        self.start_button = ttk.Button(
            actions,
            text="开始下载",
            style="Accent.TButton",
            command=self._start,
        )
        self.start_button.grid(row=0, column=0, padx=(0, 8))
        self.cancel_button = ttk.Button(
            actions,
            text="取消任务",
            command=self._cancel,
            state="disabled",
        )
        self.cancel_button.grid(row=0, column=1, padx=(0, 8))
        self.open_button = ttk.Button(actions, text="打开下载目录", command=self._open_output)
        self.open_button.grid(row=0, column=2)

        ttk.Label(actions, textvariable=self.status_var, style="Status.TLabel").grid(
            row=0, column=3, sticky="e", padx=(16, 0)
        )

        log_frame = ttk.LabelFrame(container, text="运行记录", padding=10)
        log_frame.grid(row=3, column=0, sticky="nsew")
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)

        self.progress = ttk.Progressbar(log_frame, mode="indeterminate")
        self.progress.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))

        self.log_text = tk.Text(
            log_frame,
            height=13,
            wrap="word",
            state="disabled",
            font=("Consolas", 10),
            relief="flat",
            borderwidth=0,
        )
        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.grid(row=1, column=0, sticky="nsew")
        scrollbar.grid(row=1, column=1, sticky="ns")

    def _choose_cookie(self) -> None:
        selected = filedialog.askopenfilename(
            title="选择 Cookie 文件",
            initialdir=str(application_dir()),
            filetypes=[("Cookie 文本", "*.txt"), ("所有文件", "*.*")],
        )
        if selected:
            self.cookie_var.set(selected)

    def _choose_output(self) -> None:
        initial = self.output_var.get().strip() or str(default_download_dir())
        selected = filedialog.askdirectory(title="选择下载目录", initialdir=initial)
        if selected:
            self.output_var.set(selected)

    def _read_request(self) -> DownloadRequest:
        profile = self.profile_var.get().strip()
        if not profile:
            raise ValueError("请输入博主主页 URL 或 UID")

        try:
            start_date = date.fromisoformat(self.start_date_var.get().strip())
            end_date = date.fromisoformat(self.end_date_var.get().strip())
        except ValueError as exc:
            raise ValueError("日期格式必须为 YYYY-MM-DD") from exc

        cookie_path = Path(os.path.expandvars(self.cookie_var.get().strip())).expanduser()
        if not cookie_path.is_file():
            raise ValueError(f"找不到 Cookie 文件: {cookie_path}")

        output_text = self.output_var.get().strip()
        output_dir = Path(os.path.expandvars(output_text)).expanduser()
        if not output_dir.is_absolute():
            output_dir = application_dir() / output_dir

        return DownloadRequest(
            profile=profile,
            start_date=start_date,
            end_date=end_date,
            cookie_path=cookie_path,
            output_dir=output_dir,
        )

    def _start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        try:
            request = self._read_request()
        except ValueError as exc:
            messagebox.showerror("输入有误", str(exc), parent=self.root)
            return

        self.cancel_event.clear()
        self._set_running(True)
        self._append_log("任务开始。")
        self.worker = threading.Thread(
            target=self._run_worker,
            args=(request,),
            name="weibo-download-worker",
            daemon=True,
        )
        self.worker.start()

    def _run_worker(self, request: DownloadRequest) -> None:
        try:
            result = run_download(
                request,
                log=lambda message: self.messages.put(("log", message)),
                cancel_event=self.cancel_event,
            )
            self.messages.put(("done", result))
        except OperationCancelled:
            self.messages.put(("cancelled", None))
        except (WeiboDownloaderError, ValueError, OSError) as exc:
            self.messages.put(("error", str(exc)))
        except Exception as exc:
            self.messages.put(("error", f"未预期错误: {exc}"))

    def _drain_messages(self) -> None:
        try:
            while True:
                kind, payload = self.messages.get_nowait()
                if kind == "log":
                    self._append_log(str(payload))
                elif kind == "done":
                    self._finish_success(payload)
                elif kind == "cancelled":
                    self._finish_cancelled()
                elif kind == "error":
                    self._finish_error(str(payload))
        except queue.Empty:
            pass
        finally:
            if not self.closing:
                self.root.after(100, self._drain_messages)

    def _finish_success(self, payload: object) -> None:
        self._set_running(False)
        if not isinstance(payload, DownloadRunResult):
            self._finish_error("下载结果格式无效")
            return

        stats = payload.stats
        if stats is None:
            message = "日期范围内没有找到正文图片。"
            self._append_log(message)
            self.status_var.set("未找到图片")
            messagebox.showinfo("任务完成", message, parent=self.root)
        else:
            message = (
                f"下载 {stats.downloaded}，跳过 {stats.skipped}，"
                f"降级 {stats.degraded}，失败 {stats.failed}"
            )
            self._append_log(f"任务完成：{message}。")
            self.status_var.set("任务完成")
            if stats.failed:
                messagebox.showwarning(
                    "任务完成",
                    f"{message}。\n请查看下载目录中的失败清单。",
                    parent=self.root,
                )
            else:
                messagebox.showinfo("任务完成", message, parent=self.root)

        if self.closing:
            self.root.destroy()

    def _finish_cancelled(self) -> None:
        self._set_running(False)
        self._append_log("任务已取消。")
        self.status_var.set("已取消")
        if self.closing:
            self.root.destroy()
            return
        messagebox.showinfo("任务已取消", "当前任务已取消。", parent=self.root)

    def _finish_error(self, message: str) -> None:
        self._set_running(False)
        self._append_log(f"错误：{message}")
        self.status_var.set("发生错误")
        if self.closing:
            self.root.destroy()
            return
        messagebox.showerror("任务失败", message, parent=self.root)

    def _set_running(self, running: bool) -> None:
        state = "disabled" if running else "normal"
        for widget in self.input_widgets:
            widget.configure(state=state)
        self.start_button.configure(state="disabled" if running else "normal")
        self.cancel_button.configure(state="normal" if running else "disabled")
        if running:
            self.status_var.set("正在运行")
            self.progress.start(12)
        else:
            self.progress.stop()

    def _cancel(self) -> None:
        if self.worker and self.worker.is_alive():
            self.cancel_event.set()
            self.cancel_button.configure(state="disabled")
            self.status_var.set("正在取消")
            self._append_log("已请求取消，当前网络请求完成后停止。")

    def _append_log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message.rstrip() + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _open_output(self) -> None:
        output_text = self.output_var.get().strip() or str(default_download_dir())
        output_dir = Path(os.path.expandvars(output_text)).expanduser()
        if not output_dir.is_absolute():
            output_dir = application_dir() / output_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        startfile = getattr(os, "startfile", None)
        if startfile is not None:
            startfile(str(output_dir))
        else:
            webbrowser.open(output_dir.as_uri())

    def _on_close(self) -> None:
        if self.worker and self.worker.is_alive():
            should_close = messagebox.askyesno(
                "取消任务",
                "下载任务仍在运行，是否取消并退出？",
                parent=self.root,
            )
            if not should_close:
                return
            self.closing = True
            self.cancel_event.set()
            self.cancel_button.configure(state="disabled")
            self.status_var.set("正在取消")
            return
        self.root.destroy()


def main() -> int:
    root = tk.Tk()
    DownloaderApp(root)
    root.mainloop()
    return 0
