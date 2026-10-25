"""Nothing identifying is ever published: no names, no songs, no addresses.

An absolute rule of the owner's. Most of what it forbids cannot be written
into a test, since the test is published, so those terms live in
.local/private-terms.txt, which .local/ keeps out of git: one case-insensitive
regular expression per line, # for a comment. A worktree has no .local of its
own and reads the main checkout's. Off the owner's machine there is no .local
and nothing to check against, so that test skips, saying so; on it, a .local
without the list fails rather than skipping.

What can be checked without naming anything is checked everywhere: no real
environment file is tracked, and every email address in a tracked file, or in
a tracked file's path, is on a domain reserved for examples.

Commit messages, ref names and pull request text are not files and cannot be
seen from here; the pre-push hook in .local/hooks/ reads the same list for the
first two. Nothing reads it for a merge made on GitHub, so run this file on a
pull request's merge result before merging it there.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _terms_file() -> Path:
    # A worktree has no .local of its own, being made from what is tracked.
    # The main checkout's list applies to it all the same.
    here = ROOT / ".local" / "private-terms.txt"
    if here.is_file():
        return here
    try:
        common = subprocess.run(["git", "rev-parse", "--path-format=absolute",
                                 "--git-common-dir"], cwd=ROOT, check=True,
                                capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return here
    return Path(common).parent / ".local" / "private-terms.txt"


TERMS = _terms_file()

# RFC 2606 and RFC 6761: names that can never belong to anybody.
RESERVED = re.compile(r"(^|\.)(example\.(com|net|org)|example|invalid|test|localhost)$")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@((?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,})(?![A-Za-z0-9])")

# .env, .envrc, .env.local, .env-prod, settings.env. Not env.py or env.d.ts,
# which are code.
ENV_FILE = re.compile(r"^\.env(rc)?$|^\.env[.-].+|.+\.env$")


# A hyphen inside a word, so a word written out in syllables is read joined
# up as well: the vocabulary once reached a docstring that way.
SYLLABLE_BREAK = re.compile(r"(?<=[^\s-])-(?=[^\s-])")


def _names(term: re.Pattern, line: str) -> bool:
    """Whether a line names the term, as written or in syllables."""
    return bool(term.search(line) or term.search(SYLLABLE_BREAK.sub("", line)))


def _terms() -> list[re.Pattern]:
    lines = TERMS.read_text(encoding="utf-8-sig").splitlines()
    return [re.compile(line.strip(), re.IGNORECASE) for line in lines
            if line.strip() and not line.lstrip().startswith("#")]


def _tracked() -> list[Path]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, check=True,
                         capture_output=True).stdout.decode("utf-8")
    return [ROOT / name for name in out.split("\0") if name]


def _lines():
    """Every tracked path, as line 0 of its file, then every line of text."""
    for path in _tracked():
        rel = path.relative_to(ROOT)
        yield rel, 0, rel.as_posix()
        try:
            data = path.read_bytes()
        except OSError:
            continue  # gone from the working tree
        for number, line in enumerate(_text(data).splitlines(), start=1):
            yield rel, number, line


def _text(data: bytes) -> str:
    """A file's text in whatever it was written in.

    UTF-16 is what Windows PowerShell writes by default, and it is full of NUL
    bytes, so it is recognised first. Anything else is read as UTF-8 with NUL
    bytes dropped and undecodable bytes replaced: a file in another 8-bit
    encoding still says whatever it says in ASCII, and so does an image or a
    document carrying its author in its metadata. The pre-push hook reads
    binaries the same way.
    """
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace")
    if b"\0" in data:
        # UTF-16 without a byte order mark: ASCII text leaves every other byte
        # zero, the odd ones in little-endian and the even ones in big-endian.
        # An icon or an image can have that many zeros too, so it counts as
        # text only if nearly all of it decodes to something printable.
        for zeros, codec in ((data[1::2], "utf-16-le"), (data[0::2], "utf-16-be")):
            if len(data) >= 4 and zeros.count(0) > len(data) // 4:
                text = data.decode(codec, errors="replace")
                readable = sum(ch.isprintable() or ch in "\r\n\t" for ch in text)
                if readable >= 0.95 * len(text):
                    return text
    return data.replace(b"\0", b"").decode("utf-8", errors="replace")


def test_text_is_read_in_the_encodings_windows_writes():
    real = "someone@" + "mail.fi"
    line = real + "\n"
    for encoded in (line.encode("utf-16"), line.encode("utf-16-le"),
                    line.encode("utf-16-be"), line.encode("cp1252"),
                    line.encode("utf-8")):
        assert real in _text(encoded)
    # An image whose metadata names its author is still read for that name.
    png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x10tEXtAuthor\x00" + real.encode()
    assert real in _text(png)
    # An icon has zeros in every other byte and is still not UTF-16 text.
    icon = bytes([0, 0, 1, 0, 1, 0, 16, 16, 0, 0, 1, 0, 32, 0, 104, 4] * 4)
    assert "\x00" not in _text(icon) and not EMAIL.search(_text(icon))


def test_the_term_list_is_not_missing_where_it_belongs():
    # Off the owner's machine there is no .local and the check below skips.
    # On it, a .local without the list is a lost list, and skipping quietly
    # there would turn the one check that knows the names off unnoticed.
    if TERMS.parent.is_dir():
        assert TERMS.is_file(), f"{TERMS} is missing"


def test_the_address_pattern_can_fail():
    # It once carried a control character where \b belonged and matched
    # nothing, which made the test below pass on anything.
    real = "someone@" + "mail.fi"
    assert EMAIL.search(real)
    assert not RESERVED.search(EMAIL.search(real).group(1))
    assert RESERVED.search(EMAIL.search("someone@example.com").group(1))
    assert EMAIL.search(real + "_x"), "a word character after it must not hide it"


def test_a_word_in_syllables_is_read_joined_up():
    assert SYLLABLE_BREAK.sub("", "HEI KA-LA-KUK-KO, a-b-c") == "HEI KALAKUKKO, abc"
    assert SYLLABLE_BREAK.sub("", "a - b and --flag") == "a - b and --flag"
    term = re.compile(r"\bkalakukko\b", re.IGNORECASE)
    assert _names(term, "HEI KA-LA-KUK-KO")
    assert _names(term, "a kalakukko")
    assert not _names(term, "kala - kukko")


def test_the_environment_pattern_tells_settings_from_code():
    for name in (".env", ".envrc", ".env.local", ".env-prod", "settings.env"):
        assert ENV_FILE.search(name), name
    for name in ("env.py", "env.d.ts", "x.env.ts", "pyvenv.cfg", "environment.ts"):
        assert not ENV_FILE.search(name), name


@pytest.mark.skipif(not TERMS.is_file(),
                    reason="no .local/private-terms.txt on this machine")
def test_no_tracked_file_names_anything_private():
    terms = _terms()
    assert terms, f"{TERMS} holds no terms"
    found = [f"{path}:{number}: {term.pattern}"
             for path, number, line in _lines()
             for term in terms if _names(term, line)]
    assert not found, "private terms in tracked files:\n" + "\n".join(found)


def test_no_real_environment_file_is_tracked():
    # A .env holds the machine's real addresses and allowlist. Only the shape,
    # in a .env.example, belongs in the repository.
    tracked = [path.relative_to(ROOT) for path in _tracked()
               if ENV_FILE.search(path.name) and not path.name.endswith(".example")]
    assert not tracked, f"environment files are tracked: {tracked}"


def test_every_email_address_is_an_example():
    found = []
    for path, number, line in _lines():
        for match in EMAIL.finditer(line):
            if not RESERVED.search(match.group(1).lower()):
                found.append(f"{path}:{number}: {match.group(0)}")
    assert not found, "real-looking email addresses:\n" + "\n".join(found)
