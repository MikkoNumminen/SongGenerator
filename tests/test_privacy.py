"""Nothing identifying is ever published: no names, no songs, no addresses.

An absolute rule of the owner's. Most of what it forbids cannot be written
into a test, since the test is published, so those terms live in
.local/private-terms.txt, which .local/ keeps out of git: one case-insensitive
regular expression per line, # for a comment. On a machine without that file
there is nothing to check against and that test skips, saying so.

What can be checked without naming anything is checked everywhere: no real
environment file is tracked, and every email address in a tracked file is on a
domain reserved for examples.

Commit messages and pull request text are not files and cannot be seen from
here; the pre-push hook in .local/hooks/ reads the same list for those.
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
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@((?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,})")


def _terms() -> list[re.Pattern]:
    lines = TERMS.read_text(encoding="utf-8").splitlines()
    return [re.compile(line.strip(), re.IGNORECASE) for line in lines
            if line.strip() and not line.lstrip().startswith("#")]


def _tracked() -> list[Path]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, check=True,
                         capture_output=True).stdout.decode("utf-8")
    return [ROOT / name for name in out.split("\0") if name]


def _lines():
    for path in _tracked():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binary, or gone from the working tree
        for number, line in enumerate(text.splitlines(), start=1):
            yield path.relative_to(ROOT), number, line


@pytest.mark.skipif(not TERMS.is_file(),
                    reason="no .local/private-terms.txt on this machine")
def test_no_tracked_file_names_anything_private():
    terms = _terms()
    found = [f"{path}:{number}: {term.pattern}"
             for path, number, line in _lines()
             for term in terms if term.search(line)]
    assert not found, "private terms in tracked files:\n" + "\n".join(found)


def test_no_real_environment_file_is_tracked():
    # A .env holds the machine's real addresses and allowlist. Only the shape,
    # in a .env.example, belongs in the repository.
    tracked = [path.relative_to(ROOT) for path in _tracked()
               if re.search(r"(^|\.)env(rc)?(\.|$)", path.name)
               and not path.name.endswith(".example")]
    assert not tracked, f"environment files are tracked: {tracked}"


def test_every_email_address_is_an_example():
    found = []
    for path, number, line in _lines():
        if path.name == "package-lock.json":
            continue  # npm@version pins and registry metadata, nobody's address
        for match in EMAIL.finditer(line):
            if not RESERVED.search(match.group(1).lower()):
                found.append(f"{path}:{number}: {match.group(0)}")
    assert not found, "real-looking email addresses:\n" + "\n".join(found)
