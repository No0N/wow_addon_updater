"""
Главное окно приложения: пути WoW, чекбоксы обновления, кнопка обновления.
"""
from __future__ import annotations

import tkinter as tk
import threading
from tkinter import ttk, filedialog, messagebox

from config import load_config, save_config
from tukui import (
    get_elvui_info,
    get_installed_elvui_version,
    download_elvui_zip,
    extract_elvui_to_folder,
)
from classcodex import (
    get_classcodex_info,
    get_installed_classcodex_version,
    is_installed_classcodex_current,
    download_classcodex_zip,
    extract_classcodex_to_folder,
)
from updater import APP_VERSION, download_update, get_available_update, launch_replacement
from pathlib import Path


def _select_folder(title: str, initial_dir: str | None = None) -> str:
    initial = initial_dir or ""
    path = filedialog.askdirectory(title=title, initialdir=initial or None)
    return path or ""


class MainWindow:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("ElvUI Updater")
        self.root.minsize(480, 400)
        self.root.geometry("560x480")
        self.root.resizable(False, False)

        self.cfg = load_config()
        self._site_version: str | None = None  # версия на сайте, после проверки
        self._classcodex_site_version: str | None = None
        self._classcodex_build_id: str | None = None
        self._classcodex_local_current = False
        self._classcodex_verified_path = ""
        self._update_in_progress = False
        self._build_ui()
        self._apply_config()
        self._update_button_state()
        # Проверка версии на сайте — автоматически при запуске
        self.root.after(300, self._on_check_version)
        self.root.after(1000, lambda: self._on_check_app_update(silent=True))

    def _build_ui(self) -> None:
        main = ttk.Frame(self.root, padding=12)
        main.pack(fill=tk.BOTH, expand=True)

        # --- Версии (сайт + установленные) ---
        ver_frame = ttk.LabelFrame(main, text="Версии", padding=6)
        ver_frame.pack(fill=tk.X, pady=(0, 8))
        self.lbl_version = ttk.Label(ver_frame, text="На сайте: —")
        self.lbl_version.pack(anchor=tk.W)
        self.lbl_installed = ttk.Label(ver_frame, text="Установлено: —", font=("", 8), foreground="gray")
        self.lbl_installed.pack(anchor=tk.W)
        self.btn_check = ttk.Button(ver_frame, text="Проверить версию на сайте", command=self._on_check_version)
        self.btn_check.pack(anchor=tk.W, pady=(6, 0))
        self.btn_check_app = ttk.Button(
            ver_frame,
            text=f"Проверить обновление программы (v{APP_VERSION})",
            command=self._on_check_app_update,
        )
        self.btn_check_app.pack(anchor=tk.W, pady=(4, 0))

        # --- Папки версий игры ---
        retail_frame = ttk.LabelFrame(main, text="Папка WoW актуал (Retail)", padding=6)
        retail_frame.pack(fill=tk.X, pady=(0, 8))
        row_retail = ttk.Frame(retail_frame)
        row_retail.pack(fill=tk.X)
        self.entry_retail = ttk.Entry(row_retail)
        self.entry_retail.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        self.entry_retail.bind("<FocusOut>", lambda e: (self._save_config(), self._refresh_installed_versions(), self._update_button_state()))
        ttk.Button(row_retail, text="Обзор…", command=self._browse_retail).pack(side=tk.LEFT)

        # --- WoW Classic ---
        classic_frame = ttk.LabelFrame(main, text="Папка WoW классик", padding=6)
        classic_frame.pack(fill=tk.X, pady=(0, 8))
        row_classic = ttk.Frame(classic_frame)
        row_classic.pack(fill=tk.X)
        self.entry_classic = ttk.Entry(row_classic)
        self.entry_classic.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        self.entry_classic.bind("<FocusOut>", lambda e: (self._save_config(), self._refresh_installed_versions(), self._update_button_state()))
        ttk.Button(row_classic, text="Обзор…", command=self._browse_classic).pack(side=tk.LEFT)

        # --- Выбор аддонов ---
        addons_frame = ttk.LabelFrame(main, text="Обновлять аддоны", padding=6)
        addons_frame.pack(fill=tk.X, pady=(0, 8))
        self.var_update_retail = tk.BooleanVar(value=self.cfg.get("update_retail", True))
        self.var_update_retail.trace_add("write", lambda *a: self._update_button_state())
        ttk.Checkbutton(
            addons_frame, text="WoW Retail ElvUI",
            variable=self.var_update_retail,
        ).pack(anchor=tk.W)
        self.var_update_classic = tk.BooleanVar(value=self.cfg.get("update_classic", False))
        self.var_update_classic.trace_add("write", lambda *a: self._update_button_state())
        ttk.Checkbutton(
            addons_frame, text="WoW Classic ElvUI",
            variable=self.var_update_classic,
        ).pack(anchor=tk.W)
        self.var_update_classcodex = tk.BooleanVar(value=self.cfg.get("update_classcodex", True))
        self.var_update_classcodex.trace_add("write", lambda *a: self._update_button_state())
        ttk.Checkbutton(
            addons_frame, text="WoW Retail ClassCodex",
            variable=self.var_update_classcodex,
        ).pack(anchor=tk.W)

        # --- Обновить ---
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X, pady=(12, 8))
        self.btn_update = ttk.Button(
            btn_frame, text="Скачать и обновить",
            command=self._on_update,
        )
        self.btn_update.pack(side=tk.LEFT, padx=(0, 8))
        self.lbl_status = ttk.Label(btn_frame, text="")
        self.lbl_status.pack(side=tk.LEFT)

        # Подсказка (справа)
        hint_frame = ttk.Frame(main)
        hint_frame.pack(fill=tk.X, pady=(4, 0))
        ttk.Label(
            hint_frame,
            text="Сделано для Ванахейм",
            font=("", 8),
            foreground="gray",
        ).pack(side=tk.RIGHT)

    def _apply_config(self) -> None:
        self.entry_retail.delete(0, tk.END)
        self.entry_retail.insert(0, self.cfg.get("path_retail", ""))
        self.entry_classic.delete(0, tk.END)
        self.entry_classic.insert(0, self.cfg.get("path_classic", ""))
        self.var_update_retail.set(self.cfg.get("update_retail", True))
        self.var_update_classic.set(self.cfg.get("update_classic", False))
        self.var_update_classcodex.set(self.cfg.get("update_classcodex", True))
        self._refresh_installed_versions()

    def _save_config(self) -> None:
        self.cfg["path_retail"] = self.entry_retail.get().strip()
        self.cfg["path_classic"] = self.entry_classic.get().strip()
        self.cfg["update_retail"] = self.var_update_retail.get()
        self.cfg["update_classic"] = self.var_update_classic.get()
        self.cfg["update_classcodex"] = self.var_update_classcodex.get()
        self.cfg.pop("path_classcodex", None)
        save_config(self.cfg)

    def _browse_retail(self) -> None:
        path = _select_folder("Папка версии WoW актуал (_retail_)", self.entry_retail.get().strip())
        if path:
            self.entry_retail.delete(0, tk.END)
            self.entry_retail.insert(0, path)
            self._save_config()
            self._refresh_installed_versions()
            self._update_button_state()

    def _browse_classic(self) -> None:
        path = _select_folder("Папка версии WoW классик", self.entry_classic.get().strip())
        if path:
            self.entry_classic.delete(0, tk.END)
            self.entry_classic.insert(0, path)
            self._save_config()
            self._refresh_installed_versions()
            self._update_button_state()

    def _update_button_state(self) -> None:
        """Включить «Скачать и обновить», только если есть что обновлять (версия отличается или ElvUI не установлен)."""
        if self._update_in_progress:
            self.btn_update.config(state="disabled")
            return
        paths_to_update: list[str] = []
        if self.var_update_retail.get() and self.entry_retail.get().strip():
            paths_to_update.append(self.entry_retail.get().strip())
        if self.var_update_classic.get() and self.entry_classic.get().strip():
            paths_to_update.append(self.entry_classic.get().strip())
        classcodex_path = self.entry_retail.get().strip()
        classcodex_selected = self.var_update_classcodex.get() and bool(classcodex_path)
        if not paths_to_update and not classcodex_selected:
            self.btn_update.config(state="disabled")
            return
        if (paths_to_update and self._site_version is None) or (
            classcodex_selected and self._classcodex_site_version is None
        ):
            self.btn_update.config(state="normal")
            return
        need_elvui_update = any(
            get_installed_elvui_version(Path(p)) != self._site_version
            for p in paths_to_update
        )
        need_classcodex_update = (
            classcodex_selected
            and (
                get_installed_classcodex_version(Path(classcodex_path))
                != self._classcodex_site_version
                or self._classcodex_verified_path != classcodex_path
                or not self._classcodex_local_current
            )
        )
        self.btn_update.config(state="normal" if need_elvui_update or need_classcodex_update else "disabled")

    def _refresh_installed_versions(self) -> None:
        """Обновить подпись установленных версий по текущим путям."""
        parts = []
        for label, path, _ in (
            ("Retail", self.entry_retail.get().strip(), self.var_update_retail),
            ("Classic", self.entry_classic.get().strip(), self.var_update_classic),
        ):
            if not path:
                continue
            ver = get_installed_elvui_version(Path(path))
            parts.append(f"{label}: {ver if ver else 'не найден'}")
        classcodex_path = self.entry_retail.get().strip()
        if classcodex_path:
            version = get_installed_classcodex_version(Path(classcodex_path))
            parts.append(f"ClassCodex: {version if version else 'не найден'}")
        self.lbl_installed.config(
            text="Установлено: " + (" | ".join(parts) if parts else "—")
        )

    def _on_check_version(self) -> None:
        self.lbl_version.config(text="Проверка…")
        self.root.update()
        try:
            info = get_elvui_info()
            classcodex_info = get_classcodex_info()
            self._site_version = info.version
            self._classcodex_site_version = classcodex_info.version
            self._classcodex_build_id = classcodex_info.build_id
            classcodex_path = self.entry_retail.get().strip()
            self._classcodex_verified_path = classcodex_path
            self._classcodex_local_current = bool(classcodex_path) and is_installed_classcodex_current(
                Path(classcodex_path), classcodex_info
            )
            if self._classcodex_local_current:
                self.cfg["classcodex_build_id"] = classcodex_info.build_id
                save_config(self.cfg)
            self._refresh_installed_versions()
            site_text = (
                f"На сайте: ElvUI {info.version} | ClassCodex {classcodex_info.version}"
            )
            self.lbl_version.config(text=site_text)
            self._update_button_state()
            # Подсказка: нужное ли обновление (если есть установленные версии)
            retail_p = self.entry_retail.get().strip()
            classic_p = self.entry_classic.get().strip()
            need_update = False
            for p, selected in (
                (retail_p, self.var_update_retail.get()),
                (classic_p, self.var_update_classic.get()),
            ):
                if not p or not selected:
                    continue
                inst = get_installed_elvui_version(Path(p))
                if inst and inst != info.version:
                    need_update = True
                    break
            classcodex_p = self.entry_retail.get().strip()
            if classcodex_p and self.var_update_classcodex.get():
                inst = get_installed_classcodex_version(Path(classcodex_p))
                if (
                    inst != classcodex_info.version
                    or not self._classcodex_local_current
                ):
                    need_update = True
            if need_update:
                self.lbl_installed.config(
                    text=(self.lbl_installed.cget("text") or "") + " — доступно обновление"
                )
        except Exception as e:
            self._site_version = None
            self._classcodex_site_version = None
            self._classcodex_build_id = None
            self._classcodex_local_current = False
            self._classcodex_verified_path = ""
            self.lbl_version.config(text="Ошибка проверки")
            messagebox.showerror("Ошибка", str(e))
            self._update_button_state()

    def _on_update(self) -> None:
        self._save_config()
        update_retail = self.var_update_retail.get()
        update_classic = self.var_update_classic.get()
        path_retail = self.entry_retail.get().strip()
        path_classic = self.entry_classic.get().strip()
        update_classcodex = self.var_update_classcodex.get()
        path_classcodex = path_retail

        paths: list[tuple[str, str]] = []
        if update_retail and path_retail:
            paths.append(("WoW актуал", path_retail))
        if update_classic and path_classic:
            paths.append(("WoW классик", path_classic))

        if not paths and not (update_classcodex and path_classcodex):
            messagebox.showinfo(
                "Обновление",
                "Включите чекбокс и укажите путь хотя бы для одной папки.",
            )
            return

        for label, p in paths:
            if not Path(p).exists():
                messagebox.showerror("Ошибка", f"Папка не найдена ({label}):\n{p}")
                return
        if update_classcodex and path_classcodex and not Path(path_classcodex).exists():
            messagebox.showerror("Ошибка", f"Папка не найдена (ClassCodex):\n{path_classcodex}")
            return

        self._update_in_progress = True
        self.btn_update.config(state="disabled")
        self.btn_check.config(state="disabled")
        self.lbl_status.config(text="Получение информации…")
        threading.Thread(
            target=self._perform_update,
            args=(paths, update_classcodex and bool(path_classcodex), path_classcodex),
            daemon=True,
        ).start()

    def _set_status_from_worker(self, text: str) -> None:
        try:
            self.root.after(0, lambda: self.lbl_status.config(text=text))
        except tk.TclError:
            pass

    def _on_check_app_update(self, silent: bool = False) -> None:
        """Проверить последний GitHub Release, не блокируя интерфейс."""
        self.btn_check_app.config(state="disabled")
        threading.Thread(
            target=self._check_app_update_worker,
            args=(silent,),
            daemon=True,
        ).start()

    def _check_app_update_worker(self, silent: bool) -> None:
        try:
            update = get_available_update()
        except Exception as exc:
            self.root.after(0, lambda error=exc: self._finish_app_update_check(None, error, silent))
        else:
            self.root.after(0, lambda: self._finish_app_update_check(update, None, silent))

    def _finish_app_update_check(self, update, error: Exception | None, silent: bool) -> None:
        self.btn_check_app.config(state="normal")
        if error:
            if not silent:
                messagebox.showerror("Обновление программы", str(error))
            return
        if update is None:
            if not silent:
                messagebox.showinfo("Обновление программы", "Установлена последняя версия.")
            return
        notes = update.notes.strip()
        message = f"Доступна версия {update.version}. Обновить программу сейчас?"
        if notes:
            message += "\n\n" + notes[:1000]
        if messagebox.askyesno("Обновление программы", message):
            self.btn_check_app.config(state="disabled")
            self.lbl_status.config(text="Скачивание обновления программы…")
            threading.Thread(target=self._install_app_update_worker, args=(update,), daemon=True).start()

    def _install_app_update_worker(self, update) -> None:
        try:
            downloaded = download_update(update)
            launch_replacement(downloaded)
        except Exception as exc:
            self.root.after(0, lambda error=exc: self._app_update_failed(error))
        else:
            self.root.after(0, self.root.destroy)

    def _app_update_failed(self, error: Exception) -> None:
        self.btn_check_app.config(state="normal")
        self.lbl_status.config(text="")
        messagebox.showerror("Обновление программы", str(error))

    def _perform_update(
        self,
        paths: list[tuple[str, str]],
        update_classcodex: bool,
        path_classcodex: str,
    ) -> None:
        """Скачать и установить аддоны вне потока интерфейса."""
        info = None
        classcodex_info = None
        errors: list[str] = []
        updated: list[str] = []
        try:
            info = get_elvui_info() if paths else None
            classcodex_info = get_classcodex_info() if update_classcodex else None
        except Exception as e:
            errors.append(str(e))
            self.root.after(0, lambda: self._finish_update(info, classcodex_info, updated, errors))
            return

        if info and any(get_installed_elvui_version(Path(folder)) != info.version for _, folder in paths):
            self._set_status_from_worker("Скачивание ElvUI…")
            try:
                zip_data = download_elvui_zip(info.download_url)
            except Exception as e:
                errors.append(f"ElvUI: {e}")
            else:
                self._set_status_from_worker("Установка ElvUI…")
                for label, folder in paths:
                    if get_installed_elvui_version(Path(folder)) == info.version:
                        continue
                    try:
                        extract_elvui_to_folder(zip_data, Path(folder))
                        updated.append(f"ElvUI {info.version} ({label})")
                    except Exception as e:
                        errors.append(f"{label}: {e}")

        if classcodex_info and (
            not is_installed_classcodex_current(Path(path_classcodex), classcodex_info)
        ):
            self._set_status_from_worker("Скачивание ClassCodex с U.GG…")
            try:
                classcodex_zip = download_classcodex_zip(
                    classcodex_info,
                    progress_callback=lambda done, total: self._set_status_from_worker(
                        f"Скачивание ClassCodex: {done} из {total}…"
                    ),
                    target_dir=Path(path_classcodex),
                )
                self._set_status_from_worker("Установка ClassCodex…")
                extract_classcodex_to_folder(
                    classcodex_zip,
                    Path(path_classcodex),
                    allow_partial=True,
                )
                updated.append(f"ClassCodex {classcodex_info.version}")
            except Exception as e:
                errors.append(f"ClassCodex: {e}")

        self.root.after(0, lambda: self._finish_update(info, classcodex_info, updated, errors))

    def _finish_update(self, info, classcodex_info, updated: list[str], errors: list[str]) -> None:
        """Завершить фоновое обновление в потоке Tkinter."""
        self._update_in_progress = False
        self.lbl_status.config(text="")
        self.btn_check.config(state="normal")
        if classcodex_info and not any(error.startswith("ClassCodex:") for error in errors):
            self.cfg["classcodex_build_id"] = classcodex_info.build_id
            save_config(self.cfg)
            self._classcodex_local_current = True
            self._classcodex_verified_path = self.entry_retail.get().strip()
        if info:
            self._site_version = info.version
        if classcodex_info:
            self._classcodex_site_version = classcodex_info.version
            self._classcodex_build_id = classcodex_info.build_id
        self._refresh_installed_versions()
        self._update_button_state()
        if errors:
            messagebox.showerror("Ошибка обновления", "\n".join(errors))
        else:
            messagebox.showinfo(
                "Готово",
                "Обновлено:\n" + ("\n".join(updated) if updated else "Все выбранные аддоны уже актуальны."),
            )

    def run(self) -> None:
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.mainloop()

    def _on_close(self) -> None:
        self._save_config()
        self.root.destroy()


def run_app() -> None:
    app = MainWindow()
    app.run()
