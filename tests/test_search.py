"""Unit tests for Sherlock's search channels. No GTK required."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sherlock.search import (
    load_applications,
    search_apps,
    search_files,
    web_result,
)


DESKTOP = """[Desktop Entry]
Type=Application
Name=Text Editor
GenericName=Editor
Comment=Edit plain text
Keywords=text;notes;
Icon=accessories-text-editor
"""

HIDDEN = """[Desktop Entry]
Type=Application
Name=Secret Tool
NoDisplay=true
"""


class SearchTests(unittest.TestCase):
    def test_apps_match_name_generic_comment_keywords(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            apps = root / "applications"
            apps.mkdir()
            (apps / "editor.desktop").write_text(DESKTOP, encoding="utf-8")
            (apps / "secret.desktop").write_text(HIDDEN, encoding="utf-8")
            (apps / "readme.txt").write_text("nope", encoding="utf-8")
            loaded = load_applications([apps])
            self.assertEqual([item.name for item in loaded], ["Text Editor"])
            self.assertEqual(search_apps(loaded, "text")[0].desktop_id, "editor.desktop")
            self.assertEqual(search_apps(loaded, "notes")[0].title, "Text Editor")
            self.assertEqual(search_apps(loaded, "plain")[0].title, "Text Editor")
            self.assertEqual(search_apps(loaded, "editor")[0].title, "Text Editor")
            self.assertEqual(search_apps(loaded, "secret"), [])
            self.assertEqual(search_apps(loaded, ""), [])

    def test_user_desktop_overrides_same_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            system = root / "system"
            user = root / "user"
            system.mkdir()
            user.mkdir()
            (system / "app.desktop").write_text(
                "[Desktop Entry]\nType=Application\nName=System Name\n",
                encoding="utf-8",
            )
            (user / "app.desktop").write_text(
                "[Desktop Entry]\nType=Application\nName=User Name\n",
                encoding="utf-8",
            )
            loaded = load_applications([system, user])
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].name, "User Name")

    def test_only_show_in(self):
        with tempfile.TemporaryDirectory() as tmp:
            apps = Path(tmp)
            (apps / "kde.desktop").write_text(
                "[Desktop Entry]\nType=Application\nName=K Thing\nOnlyShowIn=KDE;\n",
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "GNOME"}):
                self.assertEqual(load_applications([apps]), [])
            with mock.patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "KDE"}):
                self.assertEqual(load_applications([apps])[0].name, "K Thing")

    def test_web_is_a_single_duckduckgo_url(self):
        self.assertIsNone(web_result("  "))
        item = web_result("cats & dogs")
        self.assertEqual(item.kind, "web")
        self.assertEqual(item.url, "https://duckduckgo.com/?q=cats+%26+dogs")
        self.assertIn("cats & dogs", item.title)

    def test_file_walk_is_bounded_to_home_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            docs = home / "Documents"
            docs.mkdir()
            (docs / "Holiday Budget.txt").write_text("x", encoding="utf-8")
            nested = docs / "node_modules"
            nested.mkdir()
            (nested / "Holiday-skip.txt").write_text("x", encoding="utf-8")
            (home / "elsewhere").mkdir()
            (home / "elsewhere" / "Holiday.txt").write_text("x", encoding="utf-8")
            with mock.patch("sherlock.search._which", return_value=None):
                found = search_files("holiday", home=home)
            paths = [item.path for item in found.results]
            self.assertEqual(found.backend, "walk")
            self.assertEqual(paths, [str(docs / "Holiday Budget.txt")])

    def test_tracker_results_win_over_walk(self):
        proc = subprocess.CompletedProcess(
            args=["tracker3"],
            returncode=0,
            stdout="/home/me/Documents/notes.txt\n",
            stderr="",
        )
        def which(name):
            return "/usr/bin/tracker3" if name == "tracker3" else None
        with mock.patch("sherlock.search._which", side_effect=which), \
             mock.patch("sherlock.search._run", return_value=proc):
            found = search_files("notes")
        self.assertEqual(found.backend, "tracker3")
        self.assertEqual(found.results[0].path, "/home/me/Documents/notes.txt")

    def test_missing_tracker_subcommand_falls_through_to_plocate(self):
        calls = []

        def which(name):
            if name in {"tracker3", "plocate"}:
                return "/usr/bin/" + name
            return None

        def run(argv, timeout=3.0):
            calls.append(argv[0])
            if argv[0] == "tracker3":
                return subprocess.CompletedProcess(argv, 1, "", "Unknown command: search")
            return subprocess.CompletedProcess(argv, 0, "/tmp/found.txt\n", "")

        with mock.patch("sherlock.search._which", side_effect=which), \
             mock.patch("sherlock.search._run", side_effect=run):
            found = search_files("found")
        self.assertEqual(calls, ["tracker3", "plocate"])
        self.assertEqual(found.backend, "plocate")
        self.assertEqual(found.results[0].path, "/tmp/found.txt")


if __name__ == "__main__":
    unittest.main()
