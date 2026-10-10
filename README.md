# Sherlock

A small Fedora search window in the spirit of classic Mac OS Sherlock (the utility that lived before Spotlight). One compact window stays in front of other windows when the toolkit allows it. You type, and results update from three channels:

| Channel | What it does |
| --- | --- |
| Apps | Reads `.desktop` files and launches the one you pick. |
| Files | Searches with an index if you have one, otherwise a short folder scan. |
| Web | One row, **Search the web for …**, which opens DuckDuckGo in your browser. |

Sherlock does not download or scrape web pages. The web channel is a single action, not a live web index.

The window is about 640×420. The search box is focused when the window opens. Results refresh after a short pause (180 ms) so typing stays responsive.

| Key | Action |
| --- | --- |
| Esc | Close the window |
| Enter | Activate the selected row |
| Up / Down | Move the selection |

Activating a row launches it and closes Sherlock.

## Download

Get the latest package from the [Releases page](https://github.com/gauthampalaniappan/sherlock/releases/latest):

| System | File | Install |
| --- | --- | --- |
| Fedora | `sherlock-search-<version>-1.<fc>.noarch.rpm` | `sudo dnf install ./sherlock-search-*.rpm` |
| Debian 13, Ubuntu 24.04 or newer | `sherlock-search_<version>-1_all.deb` | `sudo apt install ./sherlock-search_*.deb` |

Both packages pull in GTK 4 and libadwaita automatically. Open **Sherlock** from the app grid, or run `sherlock-search`.

The package and command are named `sherlock-search` because Debian and Ubuntu already have an unrelated package called `sherlock` (a username-search tool). The app itself is still called Sherlock.

Sherlock is Linux only: it searches `.desktop` launchers and Linux file indexes, which Windows and macOS do not have.

## Packages (running from source)

Install these on Fedora. Names were checked against [packages.fedoraproject.org](https://packages.fedoraproject.org/) and the [Fedora PyGObject page](https://developer.fedoraproject.org/tech/languages/python/pygobject.html) in September 2026:

```sh
sudo dnf install python3-gobject gtk4 libadwaita
```

- `python3-gobject` — Python bindings (PyGObject).
- `gtk4` — GTK 4, including the `Gtk-4.0` typelib.
- `libadwaita` — GNOME styling, including the `Adw-1` typelib.

You do not need the `-devel` packages to run Sherlock.

File search is optional. Install any of these that you want; Sherlock uses the first one it can actually run:

```sh
sudo dnf install plocate
```

`plocate` is the fast file index. After installing it, build the database once (this needs root):

```sh
sudo updatedb
```

On current Fedora, Tracker has been renamed. The `tinysparql` package `Provides: tracker`, and its program is `tinysparql`, not `tracker3`:

```sh
sudo dnf install tinysparql
```

Sherlock tries `tracker3 search` first when that program is on `PATH` (older installs), then `tinysparql search`. The tinysparql 3.12 package file list has no `search` manual page, so that subcommand may be gone. If the command fails, Sherlock does not stop; it tries `plocate`, then `locate`, then a folder walk. `xdg-open`, from the `xdg-utils` package, is only a fallback if GIO cannot open a file or URL. A normal Fedora desktop already opens files through GIO.

## Run

From this directory, without installing:

```sh
./run.sh
```

That is `python3 -m sherlock`. The search box takes focus immediately.

## Install for your user

This does not need root and does not copy anything into system directories. It writes:

- `~/.local/share/applications/sherlock.desktop` (or `$XDG_DATA_HOME/applications/`)
- `~/.local/share/icons/hicolor/scalable/apps/sherlock.svg`

The desktop file’s `Exec` line points back at `run.sh` in this directory, so leave the source tree where it is.

```sh
./install.sh
```

Then open **Sherlock** from the app grid. If the icon does not show up immediately, log out and back in, or run:

```sh
update-desktop-database "${XDG_DATA_HOME:-$HOME/.local/share}/applications"
```

To uninstall, delete those two files. Nothing else was registered.

## How the channels work

**Apps.** Sherlock scans `applications` folders from `$XDG_DATA_DIRS` and `$XDG_DATA_HOME`, and always includes `/usr/share/applications` and `~/.local/share/applications`. A later file with the same desktop id replaces an earlier one, so your `~/.local` copy wins. It keeps `Type=Application` entries and skips `Hidden` and `NoDisplay`. It matches Name, GenericName, Comment, and Keywords, including the locale from `LANG` when a translated key exists. Activating a row uses `Gio.DesktopAppInfo` (the same path as `gtk-launch`). If that fails, it tries `gtk4-launch`, then `gtk-launch`.

**Files.** Order: `tracker3 search`, `tinysparql search`, `plocate`, `locate`. Each command is killed after 3 seconds. If none of those programs exist, or they fail to run (unknown subcommand, missing index), Sherlock walks `~/Documents`, `~/Downloads`, and `~/Desktop` only. The walk skips hidden directories and a few heavy names (`.git`, `node_modules`, `__pycache__`), stops after 6000 entries or 1.5 seconds, and returns at most 40 paths. Activating a row opens it with the default app.

**Web.** The row opens `https://duckduckgo.com/?q=…` in the default browser. No request is made from Sherlock itself.

## Limits

- **Always on top.** GTK 4 does not document `Window.set_keep_above` (the GTK 3 call was removed). Sherlock calls that method if the installed GTK still has it. On a stock GTK 4 session, especially Wayland, the window is a normal window: it opens focused and on top, but the compositor may cover it later. On GNOME you can right-click the title bar and choose **Always on Top**.
- **File index.** An installed but empty `plocate` database returns no files and Sherlock will not also walk your folders, because an empty index is a real answer. Run `sudo updatedb`, or uninstall `plocate` if you want the folder walk.
- **Tracker on Fedora.** `tracker3` was not in the `tinysparql` package file list checked for Rawhide (September 2026). The fallback path above covers that.
- **Scope of the folder walk.** Only Documents, Downloads, and Desktop. It will not search all of your home directory.
- **One instance.** A second launch raises the existing window.

## Layout

```
sherlock/           Python package
data/sherlock.desktop.in
data/sherlock.svg
data/sherlock-search.desktop         launcher used by the .rpm/.deb packages
data/sherlock-search.metainfo.xml    app details shown by GNOME Software
run.sh
install.sh
tests/test_search.py
packaging/linux/                     .rpm and .deb build script and recipes
.github/workflows/release.yml        builds both packages on a version tag
```

## Releasing

1. Bump `__version__` in `sherlock/__init__.py`.
2. Add a line for that version to `data/sherlock-search.metainfo.xml`, e.g. `<release version="1.1.0" date="2026-11-01"/>` (newest first).
3. Commit and push to `main`.
4. On GitHub, open **Actions → Release → Run workflow**, tick **Create draft release**, and run it (pushing a tag such as `v1.1.0` does the same).
5. GitHub Actions runs the tests, builds the `.rpm` (in Fedora) and `.deb` (on Ubuntu 24.04), installs and launches each one, and creates a **draft** release. Check it on the Releases page, then press **Publish**; GitHub creates the tag at that moment.

Running the workflow without the tick only builds and tests; the packages appear as artifacts on that run. To build locally: `packaging/linux/build-packages.sh` (needs `dpkg-deb` and/or `rpmbuild`), output goes to `release/`.

## License

MIT. See `LICENSE`.
