"""SHIMMER_CONFIG_DIR moves settings and projects, so a second copy of
Shimmer (the rebuild, while it is being built) never touches the everyday
app's (docs/ARCHITECTURE.md §19.1 item 4)."""
import os

from shimmer import projects_store, settings_store


def test_settings_and_projects_follow_the_override(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIMMER_CONFIG_DIR", str(tmp_path))
    assert settings_store._settings_path() == os.path.join(str(tmp_path), "settings.json")
    assert projects_store._projects_dir() == os.path.join(str(tmp_path), "projects")


def test_without_the_override_the_usual_folder_is_used(monkeypatch):
    monkeypatch.delenv("SHIMMER_CONFIG_DIR", raising=False)
    assert os.path.basename(settings_store._settings_dir()).lower() == "shimmer"


def test_a_blank_override_is_ignored(monkeypatch):
    monkeypatch.setenv("SHIMMER_CONFIG_DIR", "  ")
    assert os.path.basename(settings_store._settings_dir()).lower() == "shimmer"
