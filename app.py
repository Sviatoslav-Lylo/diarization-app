"""Простий tkinter-інтерфейс: YouTube-посилання або файл -> двоканальний WAV."""
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import media

APP_DIR = Path(__file__).resolve().parent
DEFAULT_OUT = APP_DIR / "output"
FILE_TYPES = [
    (
        "Аудіо та відео",
        "*.mp3 *.wav *.m4a *.aac *.flac *.ogg *.opus *.wma "
        "*.mp4 *.mkv *.mov *.avi *.webm",
    ),
    ("Усі файли", "*.*"),
]


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Speaker Splitter — розділення спікерів по каналах")
        self.minsize(640, 460)
        self.q = queue.Queue()
        self.busy = False
        self.last_dir = None

        self.url_var = tk.StringVar()
        self.file_var = tk.StringVar()
        self.out_var = tk.StringVar(value=str(DEFAULT_OUT))
        self.device_var = tk.StringVar(value="Авто (GPU, якщо є)")
        self.device_info_var = tk.StringVar(value="Пристрій: визначається…")
        self.status_var = tk.StringVar(value="Готово до роботи.")

        self._build_ui()
        self.after(150, self._poll)

        if not (APP_DIR / ".env").exists():
            self._log("УВАГА: файл .env не знайдено. Створіть його з .env.example і вкажіть HF_TOKEN.")
        threading.Thread(target=self._detect_device, daemon=True).start()

    # ---------- UI ----------
    def _build_ui(self):
        frame = ttk.Frame(self, padding=12)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(7, weight=1)

        ttk.Label(frame, text="Посилання на YouTube:").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(frame, textvariable=self.url_var).grid(row=0, column=1, columnspan=2, sticky="ew", pady=4)

        ttk.Label(frame, text="…або файл (аудіо/відео):").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(frame, textvariable=self.file_var).grid(row=1, column=1, sticky="ew", pady=4)
        ttk.Button(frame, text="Обрати…", command=self._browse_file).grid(row=1, column=2, padx=(6, 0))

        ttk.Label(frame, text="Папка результату:").grid(row=2, column=0, sticky="w", pady=4)
        ttk.Entry(frame, textvariable=self.out_var).grid(row=2, column=1, sticky="ew", pady=4)
        ttk.Button(frame, text="Обрати…", command=self._browse_out).grid(row=2, column=2, padx=(6, 0))

        ttk.Label(frame, text="Обчислення:").grid(row=3, column=0, sticky="w", pady=4)
        combo = ttk.Combobox(
            frame,
            textvariable=self.device_var,
            values=["Авто (GPU, якщо є)", "Тільки CPU"],
            state="readonly",
            width=22,
        )
        combo.grid(row=3, column=1, sticky="w", pady=4)
        ttk.Label(frame, textvariable=self.device_info_var).grid(row=3, column=2, sticky="e")

        buttons = ttk.Frame(frame)
        buttons.grid(row=4, column=0, columnspan=3, sticky="w", pady=8)
        self.start_btn = ttk.Button(buttons, text="Старт", command=self._start)
        self.start_btn.pack(side="left")
        self.open_btn = ttk.Button(buttons, text="Відкрити папку", command=self._open_folder, state="disabled")
        self.open_btn.pack(side="left", padx=8)

        self.progress = ttk.Progressbar(frame, mode="indeterminate")
        self.progress.grid(row=5, column=0, columnspan=3, sticky="ew", pady=4)

        ttk.Label(frame, textvariable=self.status_var, wraplength=600).grid(
            row=6, column=0, columnspan=3, sticky="w", pady=4
        )

        log_frame = ttk.Frame(frame)
        log_frame.grid(row=7, column=0, columnspan=3, sticky="nsew")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log_text = tk.Text(log_frame, height=8, state="disabled", wrap="word")
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scroll.set)

    def _log(self, text):
        stamp = time.strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{stamp}] {text}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _browse_file(self):
        path = filedialog.askopenfilename(title="Оберіть аудіо або відео", filetypes=FILE_TYPES)
        if path:
            self.file_var.set(path)

    def _browse_out(self):
        path = filedialog.askdirectory(title="Оберіть папку для результату")
        if path:
            self.out_var.set(path)

    def _set_busy(self, busy):
        self.busy = busy
        self.start_btn.configure(state="disabled" if busy else "normal")
        if busy:
            self.open_btn.configure(state="disabled")
            self.progress.start(12)
        else:
            self.progress.stop()

    # ---------- дії ----------
    def _detect_device(self):
        try:
            import diarizer  # важкий імпорт (torch) — у фоні, щоб вікно з'явилось швидко

            self.q.put(("device", f"Пристрій: {diarizer.get_device_info()}"))
        except Exception as e:
            self.q.put(("device", "Пристрій: невідомо"))
            self.q.put(("status", f"Помилка імпорту бібліотек: {e}", True))

    def _start(self):
        if self.busy:
            return
        url = self.url_var.get().strip()
        file = self.file_var.get().strip().strip('"')
        out_dir = self.out_var.get().strip()

        if not url and not file:
            messagebox.showwarning("Немає входу", "Вставте посилання на YouTube або оберіть файл.")
            return
        if url and file:
            messagebox.showwarning("Забагато входів", "Вкажіть лише одне: або посилання, або файл.")
            return
        if url and not media.is_url(url):
            messagebox.showwarning("Некоректне посилання", "Посилання має починатися з http:// або https://")
            return
        if file and not Path(file).is_file():
            messagebox.showwarning("Файл не знайдено", f"Файл не існує:\n{file}")
            return
        if not out_dir:
            messagebox.showwarning("Немає папки", "Оберіть папку для результату.")
            return

        device_pref = "cpu" if self.device_var.get().startswith("Тільки") else "auto"
        self._set_busy(True)
        self.status_var.set("Починаю…")
        self._log("Старт обробки.")
        threading.Thread(
            target=self._worker, args=(url, file, Path(out_dir), device_pref), daemon=True
        ).start()

    def _worker(self, url, file, out_dir, device_pref):
        def status(text, log=True):
            self.q.put(("status", text, log))

        started = time.time()
        try:
            import diarizer

            out_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
                if url:
                    src, name = media.download_youtube(url, tmp, status)
                else:
                    src, name = Path(file), Path(file).stem

                status("Конвертація аудіо (ffmpeg)…")
                wav = media.to_wav(src, tmp)

                target = diarizer.unique_path(
                    out_dir / f"{media.safe_filename(name)}_stereo_speakers.wav"
                )
                result = diarizer.diarize_to_stereo(wav, target, device_pref, status)

            result["elapsed"] = time.time() - started
            self.q.put(("done", result))
        except Exception as e:
            traceback.print_exc()
            self.q.put(("error", str(e)))

    def _poll(self):
        try:
            while True:
                msg = self.q.get_nowait()
                kind = msg[0]
                if kind == "status":
                    self.status_var.set(msg[1])
                    if msg[2]:
                        self._log(msg[1])
                elif kind == "device":
                    self.device_info_var.set(msg[1])
                elif kind == "done":
                    self._on_done(msg[1])
                elif kind == "error":
                    self._on_error(msg[1])
        except queue.Empty:
            pass
        self.after(150, self._poll)

    def _on_done(self, result):
        self._set_busy(False)
        path = Path(result["path"])
        self.last_dir = str(path.parent)
        mins, secs = divmod(int(result["elapsed"]), 60)
        text = (
            f"Готово ({mins:02d}:{secs:02d}). Ліво = {result['speakers'][0]}, "
            f"право = {result['speakers'][1]}.\nФайл: {path}"
        )
        self.status_var.set(text)
        self._log(text)
        self.open_btn.configure(state="normal")

    def _on_error(self, message):
        self._set_busy(False)
        self.status_var.set("Помилка. Деталі в журналі.")
        self._log(f"ПОМИЛКА: {message}")
        messagebox.showerror("Помилка", message)

    def _open_folder(self):
        if not self.last_dir:
            return
        if sys.platform.startswith("win"):
            os.startfile(self.last_dir)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", self.last_dir])
        else:
            subprocess.Popen(["xdg-open", self.last_dir])


if __name__ == "__main__":
    App().mainloop()
