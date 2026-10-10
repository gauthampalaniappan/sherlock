"""GTK4 + libadwaita window for Sherlock."""

from __future__ import annotations

import shutil
import subprocess
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from sherlock.search import (
    FileSearch,
    Result,
    load_applications,
    search_apps,
    search_files,
    web_result,
)

DEBOUNCE_MS = 180
APP_ID = "local.sherlock.Sherlock"


def _keep_above(window: Gtk.Window) -> bool:
    """Ask the window to stay above others, when this GTK build allows it.

    GTK 4 removed the portable keep-above API (there is no Window.set_keep_above
    in the docs). Call it if a future or patched build still exposes it.
    """
    method = getattr(window, "set_keep_above", None)
    if not callable(method):
        return False
    try:
        method(True)
    except Exception:
        return False
    return True


def launch_result(result: Result) -> None:
    if result.kind == "app":
        _launch_app(result.desktop_id, result.path)
    elif result.kind == "file" and result.path:
        _open_uri(Gio.File.new_for_path(result.path).get_uri(), result.path)
    elif result.kind == "web" and result.url:
        _open_uri(result.url, None)


def _launch_app(desktop_id: str, path: str) -> None:
    info = None
    if desktop_id:
        info = Gio.DesktopAppInfo.new(desktop_id)
    if info is None and path:
        try:
            info = Gio.DesktopAppInfo.new_from_filename(path)
        except GLib.Error:
            info = None
    if info is not None:
        info.launch([], None)
        return
    for program in ("gtk4-launch", "gtk-launch"):
        if desktop_id and shutil.which(program):
            subprocess.Popen([program, desktop_id], start_new_session=True)
            return
    raise RuntimeError(f"Could not launch {desktop_id or path}")


def _open_uri(uri: str, fallback_path: str | None) -> None:
    try:
        Gio.AppInfo.launch_default_for_uri(uri, None)
        return
    except GLib.Error:
        pass
    if shutil.which("xdg-open"):
        target = fallback_path or uri
        subprocess.Popen(["xdg-open", target], start_new_session=True)
        return
    raise RuntimeError(f"Could not open {uri}")


class SherlockWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application) -> None:
        super().__init__(application=app, title="Sherlock", default_width=640, default_height=420)
        self._alive = True
        self._channel = "apps"
        self._apps: list = []
        self._generation = 0
        self._debounce = 0
        self._keep_above = _keep_above(self)

        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title="Sherlock", subtitle=""))

        self.entry = Gtk.SearchEntry(placeholder_text="Search", hexpand=True)
        self.entry.add_css_class("sherlock-search")
        self.entry.connect("search-changed", self._on_query_changed)

        self._apps_btn = Gtk.ToggleButton(label="Apps")
        self._files_btn = Gtk.ToggleButton(label="Files")
        self._web_btn = Gtk.ToggleButton(label="Web")
        self._files_btn.set_group(self._apps_btn)
        self._web_btn.set_group(self._apps_btn)
        self._apps_btn.set_active(True)
        channels = Gtk.Box(css_classes=["linked"], halign=Gtk.Align.CENTER)
        channels.add_css_class("sherlock-channels")
        for button in (self._apps_btn, self._files_btn, self._web_btn):
            channels.append(button)
        self._apps_btn.connect("toggled", self._on_channel, "apps")
        self._files_btn.connect("toggled", self._on_channel, "files")
        self._web_btn.connect("toggled", self._on_channel, "web")

        self.listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.listbox.add_css_class("boxed-list")
        self.listbox.set_activate_on_single_click(True)
        self.listbox.connect("row-activated", self._on_row_activated)
        self.scrolled = Gtk.ScrolledWindow(vexpand=True, child=self.listbox)
        self.scrolled.add_css_class("sherlock-results")
        self.scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        self.status = Gtk.Label(xalign=0, label="Loading applications…")
        self.status.add_css_class("dim-label")
        self.status.add_css_class("sherlock-status")

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        content.append(self.entry)
        content.append(channels)
        content.append(self.scrolled)
        content.append(self.status)

        shell = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        shell.append(header)
        shell.append(content)
        self.set_content(shell)

        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)

        css = Gtk.CssProvider()
        css_bytes = b"""
            .sherlock-search { margin: 12px 12px 8px 12px; }
            .sherlock-channels { margin: 0 12px 8px 12px; }
            .sherlock-results { margin: 0 12px; }
            .sherlock-status { margin: 6px 12px 10px 12px; }
            """
        try:
            css.load_from_data(css_bytes, len(css_bytes))
        except TypeError:
            css.load_from_data(css_bytes)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            css,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

        self.connect("show", lambda *_: self.entry.grab_focus())
        self.connect("close-request", self._on_close)
        self._show_hint("Loading applications…")
        GLib.idle_add(self._load_apps)

    def _on_close(self, *_args) -> bool:
        self._alive = False
        return False

    def _load_apps(self) -> bool:
        try:
            self._apps = load_applications()
        except Exception as exc:  # keep the window usable if one file is bad
            self._apps = []
            self.status.set_label(f"Could not read applications: {exc}")
            return False
        self._refresh()
        return False

    def _on_channel(self, button: Gtk.ToggleButton, name: str) -> None:
        if not button.get_active():
            return
        self._channel = name
        self._refresh()

    def _on_query_changed(self, *_args) -> None:
        if self._debounce:
            GLib.source_remove(self._debounce)
        self._debounce = GLib.timeout_add(DEBOUNCE_MS, self._refresh)

    def _refresh(self) -> bool:
        self._debounce = 0
        if not self._alive:
            return False
        self._generation += 1
        generation = self._generation
        query = self.entry.get_text()
        channel = self._channel
        if channel == "apps":
            results = search_apps(self._apps, query)
            if query.strip():
                note = f"{len(results)} applications"
            else:
                note = "Type to search applications"
            self._show_results(results, note)
        elif channel == "web":
            item = web_result(query)
            if item is None:
                self._show_hint("Type something to search the web")
                self.status.set_label("Web opens DuckDuckGo. Nothing is fetched in the background.")
            else:
                self._show_results([item], "Opens your browser. Sherlock does not index the web.")
        elif not query.strip():
            self._show_hint("Type to search files")
            self.status.set_label("Type to search files")
        else:
            self.status.set_label("Searching files…")
            threading.Thread(
                target=self._file_worker,
                args=(generation, query),
                daemon=True,
            ).start()
        return False

    def _file_worker(self, generation: int, query: str) -> None:
        try:
            outcome = search_files(query)
        except Exception as exc:
            outcome = FileSearch(note=f"File search failed: {exc}")
        GLib.idle_add(self._deliver_files, generation, outcome)

    def _deliver_files(self, generation: int, outcome: FileSearch) -> bool:
        if not self._alive or generation != self._generation or self._channel != "files":
            return False
        if not self.entry.get_text().strip():
            self._show_hint("Type to search files")
            self.status.set_label(outcome.note or "Type to search files")
            return False
        self._show_results(outcome.results, outcome.note or "No files")
        return False

    def _clear_rows(self) -> None:
        child = self.listbox.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.listbox.remove(child)
            child = nxt

    def _show_hint(self, text: str) -> None:
        self._clear_rows()
        row = Adw.ActionRow(title=text, activatable=False, selectable=False)
        row.result = None
        self.listbox.append(row)

    def _show_results(self, results: list[Result], note: str) -> None:
        self._clear_rows()
        if not results:
            empty = "No matches" if self.entry.get_text().strip() else note
            self._show_hint(empty)
            self.status.set_label(note)
            return
        first = None
        for result in results:
            row = Adw.ActionRow(title=result.title, subtitle=result.subtitle or "", activatable=True)
            row.add_prefix(self._icon(result.icon))
            row.result = result
            self.listbox.append(row)
            if first is None:
                first = row
        if first is not None:
            self.listbox.select_row(first)
        self.status.set_label(note)

    def _icon(self, name: str) -> Gtk.Image:
        if name and (name.startswith("/") or name.endswith((".png", ".svg", ".xpm"))):
            image = Gtk.Image.new_from_file(name)
        else:
            image = Gtk.Image.new_from_icon_name(name or "edit-find-symbolic")
        return image

    def _rows(self) -> list[Gtk.ListBoxRow]:
        rows = []
        child = self.listbox.get_first_child()
        while child is not None:
            if getattr(child, "result", None) is not None:
                rows.append(child)
            child = child.get_next_sibling()
        return rows

    def _move(self, delta: int) -> None:
        rows = self._rows()
        if not rows:
            return
        selected = self.listbox.get_selected_row()
        try:
            index = rows.index(selected)
        except ValueError:
            index = 0 if delta > 0 else len(rows) - 1
        else:
            index = max(0, min(len(rows) - 1, index + delta))
        row = rows[index]
        self.listbox.select_row(row)
        self._reveal(row)

    def _reveal(self, row: Gtk.ListBoxRow) -> None:
        try:
            ok, rect = row.compute_bounds(self.listbox)
        except Exception:
            return
        if not ok:
            return
        adj = self.scrolled.get_vadjustment()
        top = rect.origin.y
        bottom = top + rect.size.height
        value = adj.get_value()
        page = adj.get_page_size()
        if top < value:
            adj.set_value(max(0, top))
        elif bottom > value + page:
            adj.set_value(max(0, bottom - page))

    def _activate_selected(self) -> None:
        row = self.listbox.get_selected_row()
        result = getattr(row, "result", None) if row is not None else None
        if result is None:
            rows = self._rows()
            if not rows:
                return
            result = rows[0].result
        self._run_result(result)

    def _on_row_activated(self, _box, row) -> None:
        result = getattr(row, "result", None)
        if result is not None:
            self._run_result(result)

    def _run_result(self, result: Result) -> None:
        try:
            launch_result(result)
        except Exception as exc:
            self.status.set_label(str(exc))
            return
        # A search utility gets out of the way after it hands off.
        self.close()

    def _on_key(self, _controller, keyval: int, _keycode: int, _state) -> bool:
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        activate_keys = {Gdk.KEY_Return, Gdk.KEY_KP_Enter}
        iso_enter = getattr(Gdk, "KEY_ISO_Enter", None)
        if iso_enter is not None:
            activate_keys.add(iso_enter)
        if keyval in activate_keys:
            self._activate_selected()
            return True
        if keyval == Gdk.KEY_Down:
            self._move(1)
            return True
        if keyval == Gdk.KEY_Up:
            self._move(-1)
            return True
        return False


class SherlockApp(Adw.Application):
    def __init__(self) -> None:
        flags = getattr(Gio.ApplicationFlags, "DEFAULT_FLAGS", Gio.ApplicationFlags.FLAGS_NONE)
        super().__init__(application_id=APP_ID, flags=flags)
        self._window: SherlockWindow | None = None

    def do_activate(self) -> None:
        if self._window is None:
            self._window = SherlockWindow(self)
            self._window.connect("destroy", self._forget_window)
        self._window.present()
        self._window.entry.grab_focus()

    def _forget_window(self, *_args) -> None:
        self._window = None


def main() -> None:
    app = SherlockApp()
    raise SystemExit(app.run(None))
