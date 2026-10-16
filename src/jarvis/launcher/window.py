"""Small dark Settings window and explicit launcher dialogs."""

import tkinter as tk
import webbrowser
from collections.abc import Callable
from importlib.metadata import version
from pathlib import Path
from tkinter import filedialog

from jarvis.launcher.model import LauncherController
from jarvis.launcher.startup import StartupRegistration

BG = "#0A0D14"
PANEL = "#121724"
TEXT = "#DCE3ED"
DIM = "#8993A5"
ACCENT = "#3FE0D0"
FONT = ("Segoe UI", 10)
ICON_PATH = Path(__file__).with_name("assets") / "jarvis.ico"
REPOSITORY_URL = "https://github.com/AndreyLebedenko/jarvis-local"


def button(parent: tk.Misc, label: str, command: Callable[[], None]) -> tk.Button:
    return tk.Button(
        parent,
        text=label,
        command=command,
        bg=PANEL,
        fg=TEXT,
        activebackground="#1E5C56",
        activeforeground=ACCENT,
        relief="flat",
        borderwidth=0,
        padx=16,
        pady=9,
        cursor="hand2",
        font=FONT,
    )


def label(parent: tk.Misc, text: str, *, color: str = TEXT) -> tk.Label:
    return tk.Label(parent, text=text, bg=BG, fg=color, font=FONT, anchor="w")


def dialog(root: tk.Tk, title: str, message: str, *, link: str | None = None) -> None:
    window = tk.Toplevel(root)
    window.title("Jarvis")
    window.configure(bg=BG)
    window.resizable(False, False)
    window.iconbitmap(str(ICON_PATH))
    body = tk.Frame(window, bg=BG, padx=28, pady=24)
    body.pack(fill="both", expand=True)
    tk.Label(
        body, text="JARVIS", bg=BG, fg=ACCENT, font=("Segoe UI Semibold", 11)
    ).pack(anchor="w")
    tk.Label(
        body,
        text=title,
        bg=BG,
        fg=TEXT,
        font=("Segoe UI Semibold", 17),
        wraplength=450,
        justify="left",
    ).pack(anchor="w", pady=(15, 10))
    tk.Label(
        body, text=message, bg=BG, fg=DIM, font=FONT, wraplength=450, justify="left"
    ).pack(anchor="w")
    if link is not None:
        hyperlink = tk.Label(
            body,
            text=link,
            bg=BG,
            fg=ACCENT,
            font=("Segoe UI", 10, "underline"),
            cursor="hand2",
            takefocus=True,
        )
        hyperlink.pack(anchor="w", pady=(16, 0))

        def open_link(event: tk.Event) -> str:
            webbrowser.open_new_tab(link)
            return "break"

        hyperlink.bind("<Button-1>", open_link)
        hyperlink.bind("<Return>", open_link)
    button(body, "OK", window.destroy).pack(anchor="e", pady=(24, 0))
    window.bind("<Return>", lambda event: window.destroy())
    window.bind("<Escape>", lambda event: window.destroy())
    window.update_idletasks()
    center(window)
    window.grab_set()
    window.focus_force()
    root.wait_window(window)


def center(window: tk.Toplevel) -> None:
    width, height = window.winfo_reqwidth(), window.winfo_reqheight()
    x = max(0, (window.winfo_screenwidth() - width) // 2)
    y = max(0, (window.winfo_screenheight() - height) // 2)
    window.geometry(f"+{x}+{y}")


class SettingsWindow:
    def __init__(
        self,
        root: tk.Tk,
        controller: LauncherController,
        startup: StartupRegistration,
        show_error: Callable[[Exception], None],
    ) -> None:
        self.root = root
        self.controller = controller
        self.startup = startup
        self.show_error = show_error
        self.window = tk.Toplevel(root)
        self.window.title("Jarvis - Settings")
        self.window.configure(bg=BG)
        self.window.resizable(False, False)
        self.window.iconbitmap(str(ICON_PATH))
        self.home = tk.StringVar(value=str(controller.settings.home))
        self.touchstrip = tk.BooleanVar(value=controller.settings.touchstrip)
        self.autostart = tk.BooleanVar(value=startup.enabled)
        self.status = tk.StringVar()
        self._build()
        self.refresh()
        self.window.update_idletasks()
        center(self.window)

    def _build(self) -> None:
        body = tk.Frame(self.window, bg=BG, padx=28, pady=24)
        body.pack(fill="both", expand=True)
        tk.Label(
            body, text="JARVIS", bg=BG, fg=ACCENT, font=("Segoe UI Semibold", 12)
        ).pack(anchor="w")
        tk.Label(
            body,
            text="Launcher settings",
            bg=BG,
            fg=TEXT,
            font=("Segoe UI Semibold", 23),
        ).pack(anchor="w", pady=(8, 6))
        label(
            body, "Choose a mode from the tray whenever you need Jarvis.", color=DIM
        ).pack(anchor="w")
        tk.Frame(body, bg="#1C2433", height=1).pack(fill="x", pady=22)
        label(body, "Jarvis Home Folder").pack(anchor="w")
        folder = tk.Frame(body, bg=BG)
        folder.pack(fill="x", pady=(8, 4))
        self.home_entry = tk.Entry(
            folder,
            textvariable=self.home,
            width=47,
            bg=PANEL,
            fg=TEXT,
            insertbackground=ACCENT,
            relief="flat",
            font=FONT,
            disabledbackground=PANEL,
            disabledforeground=DIM,
        )
        self.home_entry.pack(side="left", fill="both", expand=True, ipady=9)
        self.browse = button(folder, "Browse...", self._browse)
        self.browse.pack(side="left", padx=(8, 0))
        self.save_home = button(body, "Save folder", self._save_home)
        self.save_home.pack(anchor="e", pady=(6, 16))
        label(
            body, "The installed Jarvis folder, including its .venv.", color=DIM
        ).pack(anchor="w")
        tk.Frame(body, bg="#1C2433", height=1).pack(fill="x", pady=20)
        self._checkbox(body, "Touchstrip", self.touchstrip, self._touchstrip)
        self._checkbox(
            body, "Load at Windows start-up", self.autostart, self._autostart
        )
        label(
            body,
            "Windows start-up loads only the launcher. It waits for your choice.",
            color=DIM,
        ).pack(anchor="w", pady=(8, 20))
        footer = tk.Frame(body, bg=BG)
        footer.pack(fill="x")
        button(footer, "About", self._about).pack(side="left")
        button(footer, "Close", self.window.destroy).pack(side="right")
        tk.Label(
            body, textvariable=self.status, bg=BG, fg=ACCENT, font=FONT, anchor="w"
        ).pack(fill="x", pady=(20, 0))

    @staticmethod
    def _checkbox(
        parent: tk.Misc,
        text: str,
        variable: tk.BooleanVar,
        command: Callable[[], None],
    ) -> None:
        tk.Checkbutton(
            parent,
            text=text,
            variable=variable,
            command=command,
            bg=BG,
            fg=TEXT,
            selectcolor=PANEL,
            activebackground=BG,
            activeforeground=ACCENT,
            font=FONT,
            anchor="w",
            cursor="hand2",
        ).pack(anchor="w", pady=5)

    def refresh(self) -> None:
        busy = self.controller.mode is not None or self.controller.exiting
        for widget in (self.home_entry, self.browse, self.save_home):
            widget.configure(state="disabled" if busy else "normal")
        self.status.set(
            "Shutting down Jarvis..."
            if self.controller.exiting
            else f"Running: {self.controller.mode.value.title()}"
            if self.controller.mode
            else "Waiting for a mode"
        )

    def _perform(self, action: Callable[[], None]) -> None:
        try:
            action()
        except (OSError, ValueError, RuntimeError) as error:
            self.show_error(error)

    def _browse(self) -> None:
        chosen = filedialog.askdirectory(
            parent=self.window,
            title="Choose Jarvis Home Folder",
            mustexist=True,
            initialdir=str(self.controller.settings.home),
        )
        if chosen:
            self.home.set(chosen)

    def _save_home(self) -> None:
        self._perform(lambda: self.controller.set_home(Path(self.home.get())))
        self.home.set(str(self.controller.settings.home))

    def _touchstrip(self) -> None:
        self._perform(lambda: self.controller.set_touchstrip(self.touchstrip.get()))
        self.touchstrip.set(self.controller.settings.touchstrip)

    def _autostart(self) -> None:
        self._perform(lambda: self.startup.set_enabled(self.autostart.get()))
        self.autostart.set(self.startup.enabled)

    def _about(self) -> None:
        dialog(
            self.root,
            "Jarvis",
            f"Local voice and vision assistant\nVersion {version('local-jarvis')}\n\n"
            "Assistant: talk to Jarvis.\nMCP: voice guide for another assistant.\n\n"
            "The launcher starts idle and never switches a running mode.",
            link=REPOSITORY_URL,
        )
