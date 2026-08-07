"""Fetching stays off the network and out of the way of what exists.

None of these touch the network: the two functions that do, `_probe` and
`_download`, are replaced with fakes. What is under test is everything the
fetch decides around them -- the filename a web title becomes, the refusal to
overwrite, the sources index gaining exactly one row, and the FetchResult a
GUI would consume instead of parsing stdout.
"""

import dataclasses
import json
from pathlib import Path

import pytest

from song_generator import fetch
from song_generator.util import slugify

URL = "https://example.com/watch?v=abc123"

INFO = {
    "title": "Example Song (Official Video)",
    "uploader": "Example Channel",
    "webpage_url": URL,
    "duration": 213.0,
    "width": 1920,
    "height": 1080,
}


@pytest.fixture
def offline(monkeypatch):
    """Replace the two network functions; count how often each runs."""
    calls = {"probe": 0, "download": 0, "info": dict(INFO)}

    def probe(url):
        calls["probe"] += 1
        return dict(calls["info"])

    def download(url, target):
        calls["download"] += 1
        target.write_bytes(b"not real video")

    monkeypatch.setattr(fetch, "_probe", probe)
    monkeypatch.setattr(fetch, "_download", download)
    return calls


def test_result_carries_what_a_gui_needs(offline, tmp_path):
    """The GUI consumes the dataclass, not stdout, so every field it would
    display has to be on the object."""
    result = fetch.fetch(URL, out_dir=tmp_path)

    assert result.path.is_file()
    assert result.path.parent == tmp_path
    assert result.slug == slugify(INFO["title"])
    assert result.title == INFO["title"]
    assert result.uploader == INFO["uploader"]
    assert result.url == URL
    assert result.duration_s == 213.0
    assert (result.width, result.height) == (1920, 1080)
    assert result.already_present is False

    # Frozen on purpose: a result is a record of what happened, and a GUI
    # holding one must not be able to drift it.
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.title = "edited"


def test_a_title_illegal_on_windows_becomes_a_sane_filename(offline, tmp_path):
    """An illegal character in a derived filename once made a write throw and
    silently abandoned an entire source. A web title can hold every character
    Windows forbids, so the filename is derived from the slug, never from the
    site's own spelling."""
    offline["info"]["title"] = 'AC/DC: "Back? <In> Black*" |1980\\'

    result = fetch.fetch(URL, out_dir=tmp_path)

    assert result.path.is_file()
    assert not set('<>:"/\\|?*') & set(result.path.name)
    assert result.path.name == f"{result.slug}.mp4"
    # The slug the whole tool keys on: slugifying the filename, as cli does,
    # must land back on the same slug.
    assert slugify(result.path.name) == result.slug


def test_an_existing_file_is_reported_and_never_overwritten(offline, tmp_path):
    """No download over it, no silent '(1)' duplicate beside it."""
    target = tmp_path / f"{slugify(INFO['title'])}.mp4"
    target.write_bytes(b"the file that was already here")

    result = fetch.fetch(URL, out_dir=tmp_path)

    assert result.already_present is True
    assert result.path == target
    assert target.read_bytes() == b"the file that was already here"
    assert offline["download"] == 0
    assert list(tmp_path.glob("*.mp4")) == [target]


def test_sources_gains_exactly_one_row_and_none_on_repeat(offline, tmp_path):
    fetch.fetch(URL, out_dir=tmp_path)
    fetch.fetch(URL, out_dir=tmp_path)  # second run: file already present

    slug = slugify(INFO["title"])
    text = (tmp_path / "SOURCES.md").read_text(encoding="utf-8")
    rows = [line for line in text.splitlines() if line.startswith(f"| `{slug}` |")]
    assert len(rows) == 1
    assert URL in rows[0]
    assert f"`{tmp_path / (slug + '.mp4')}`" in rows[0]


def test_sources_is_created_with_its_header_when_absent(offline, tmp_path):
    assert not (tmp_path / "SOURCES.md").exists()
    fetch.fetch(URL, out_dir=tmp_path)

    text = (tmp_path / "SOURCES.md").read_text(encoding="utf-8")
    assert text.startswith("# Where each song came from")
    assert "| Name | Local file | Address |" in text


def test_sources_row_lands_in_the_table_not_after_later_prose(offline, tmp_path):
    """The real index carries prose sections below its table. A row appended
    at end of file would sit outside the table it belongs to."""
    existing = (
        "# Where each song came from\n\n"
        "## Songs\n\n"
        "| Name | Local file | Address |\n"
        "|---|---|---|\n"
        "| `older_song` | `input\\older_song.mp4` | unknown |\n\n"
        "## Notes\n\n"
        "Prose that must stay below the table.\n"
    )
    (tmp_path / "SOURCES.md").write_text(existing, encoding="utf-8")

    fetch.fetch(URL, out_dir=tmp_path)

    lines = (tmp_path / "SOURCES.md").read_text(encoding="utf-8").splitlines()
    slug = slugify(INFO["title"])
    new_row = next(i for i, line in enumerate(lines)
                   if line.startswith(f"| `{slug}` |"))
    notes = lines.index("## Notes")
    older = next(i for i, line in enumerate(lines)
                 if line.startswith("| `older_song` |"))
    assert older < new_row < notes


def test_a_playlist_address_is_refused_not_guessed_at(offline, tmp_path):
    offline["info"]["_type"] = "playlist"

    with pytest.raises(fetch.FetchError, match="playlist"):
        fetch.fetch(URL, out_dir=tmp_path)
    assert offline["download"] == 0


def test_json_emits_the_documented_fields(offline, tmp_path, capsys):
    code = fetch.main([URL, "--out", str(tmp_path), "--json"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert set(payload) == {
        "path", "slug", "title", "uploader", "url",
        "duration_s", "width", "height", "already_present",
        "conflicting_url",
    }
    assert payload["title"] == INFO["title"]
    assert payload["already_present"] is False
    assert payload["conflicting_url"] is None
    assert Path(payload["path"]).is_file()


def test_cli_reports_already_present_and_still_exits_zero(offline, tmp_path, capsys):
    """Fetching the same address twice is idempotent, not an error."""
    assert fetch.main([URL, "--out", str(tmp_path)]) == 0
    capsys.readouterr()

    assert fetch.main([URL, "--out", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "already here" in out
    assert offline["download"] == 1


URL_B = "https://elsewhere.example.com/watch?v=zzz999"


def test_a_slug_collision_keeps_the_first_songs_address(offline, tmp_path):
    """Two different videos can slugify to the same name. The second fetch
    must not pair its address with the first video's file, and the first
    video's row must keep the address it had."""
    fetch.fetch(URL, out_dir=tmp_path)

    offline["info"].update({"webpage_url": URL_B,
                            "uploader": "Another Channel"})
    result = fetch.fetch(URL_B, out_dir=tmp_path)

    assert result.already_present is True
    assert result.conflicting_url == URL
    assert offline["download"] == 1  # the first video's file is untouched
    text = (tmp_path / "SOURCES.md").read_text(encoding="utf-8")
    assert URL in text
    assert URL_B not in text


def test_collision_cli_warns_on_stderr_and_exits_nonzero(offline, tmp_path, capsys):
    """The warning names both addresses and the file, and the usual advice
    to delete the file is withheld, because deleting it would destroy the
    song the index describes."""
    assert fetch.main([URL, "--out", str(tmp_path)]) == 0
    capsys.readouterr()

    offline["info"]["webpage_url"] = URL_B
    code = fetch.main([URL_B, "--out", str(tmp_path)])
    captured = capsys.readouterr()

    assert code == fetch.EXIT_ERROR
    assert URL in captured.err
    assert URL_B in captured.err
    assert f"{slugify(INFO['title'])}.mp4" in captured.err
    assert "delete the file" not in captured.out


def test_refetching_the_same_address_is_not_a_collision(offline, tmp_path):
    fetch.fetch(URL, out_dir=tmp_path)
    result = fetch.fetch(URL, out_dir=tmp_path)

    assert result.already_present is True
    assert result.conflicting_url is None


def test_an_unknown_recorded_address_is_not_a_collision(offline, tmp_path):
    """`unknown` is the placeholder for an address nobody wrote down, not an
    address that can contradict the probed one."""
    slug = slugify(INFO["title"])
    (tmp_path / f"{slug}.mp4").write_bytes(b"hand-copied, no known address")
    (tmp_path / "SOURCES.md").write_text(
        "# Where each song came from\n\n## Songs\n\n"
        "| Name | Local file | Address |\n|---|---|---|\n"
        f"| `{slug}` | `input\\{slug}.mp4` | unknown |\n",
        encoding="utf-8",
    )

    result = fetch.fetch(URL, out_dir=tmp_path)

    assert result.already_present is True
    assert result.conflicting_url is None
