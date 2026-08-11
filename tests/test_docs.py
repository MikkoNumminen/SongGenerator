"""Keep the documentation honest.

Docs rot silently, and an agent trusting a stale instruction is worse off than
one with no docs at all -- it will confidently run the wrong command. These
tests fail when the documentation and the code disagree, so drift becomes a red
test rather than someone's wasted afternoon.
"""

import re
from pathlib import Path

import pytest

from song_generator import config

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"

# Gitignored, machine-specific, and deliberately not part of the published
# module set, so the architecture map neither lists it nor should.
_LOCAL_ONLY = {"vocabulary_local"}


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("name", [
    "AGENTS.md",
    "README.md",
    "docs/GLOSSARY.md",
    "docs/ARCHITECTURE.md",
    "docs/WORKFLOWS.md",
    "docs/DATA-FORMATS.md",
    "docs/TODO.md",
    "docs/AI-FIRST.md",
])
def test_documented_files_exist(name):
    assert (ROOT / name).is_file(), f"{name} is referenced as part of the docs set"


def test_every_module_is_in_the_architecture_map():
    """A module nobody documented is a module nobody will find."""
    modules = {
        p.stem for p in (ROOT / "src" / "song_generator").glob("*.py")
        if not p.stem.startswith("__") and p.stem not in _LOCAL_ONLY
    }
    described = read(DOCS / "ARCHITECTURE.md")
    missing = sorted(m for m in modules if f"{m}.py" not in described)
    assert not missing, f"undocumented modules: {missing}"


def test_architecture_map_lists_no_module_that_was_deleted():
    modules = {p.stem for p in (ROOT / "src" / "song_generator").glob("*.py")}
    described = set(re.findall(r"`(\w+)\.py`", read(DOCS / "ARCHITECTURE.md")))
    stale = sorted(described - modules)
    assert not stale, f"documented but gone: {stale}"


def _referenced_constants(text: str) -> set[str]:
    """SCREAMING_CASE names a doc claims exist in config.

    Example filenames are excluded: an uppercase name ending in a digit is
    something like BRAVO3.wav, not a constant.
    """
    return {
        name for name in re.findall(r"\b([A-Z][A-Z0-9_]{4,})\b", text)
        if not name.startswith(("TODO", "NOTE", "MODE", "SYL", "THEN", "AAH", "AI"))
        and not name[-1].isdigit()
    }


@pytest.mark.parametrize("doc", [
    "AGENTS.md", "README.md",
    "docs/WORKFLOWS.md", "docs/GLOSSARY.md",
    "docs/ARCHITECTURE.md", "docs/DATA-FORMATS.md",
])
def test_constants_named_in_docs_actually_exist(doc):
    """Naming a constant that was renamed sends a reader hunting for nothing."""
    known = set(dir(config))
    # Words that look like constants but are prose or JSON keys.
    allowed = {
        "AGENTS", "README", "GLOSSARY", "ARCHITECTURE", "WORKFLOWS", "CLAUDE",
        "AZURE", "DESIGN",
        "DEMUCS", "WORLD", "PATH", "JSON", "LUFS", "PYTHONPATH", "GPU",
        "NVIDIA", "TSV", "BOM", "DENSITY", "CLIMAXES", "STAGE", "LISTEN",
        "FIRST", "FORMATS", "BRAVO", "OTHER", "PLAYFULNESS", "SOURCES",
        # Environment variables, like PYTHONPATH above. Named in the batch
        # runbook because setting them wrongly is what makes a parallel run
        # take the machine down.
        "CUDA_VISIBLE_DEVICES", "OMP_NUM_THREADS", "MKL_NUM_THREADS",
        # Deployment settings for the web front end and the edge, which are
        # real and checked elsewhere: SONGGEN_ALLOWED_ORIGINS is read in
        # api/app/config.py, and the other two are an injection token in
        # web/src/app/core plus the repository variable that fills it. This
        # test guards the pipeline's own constants, and pulling those two
        # trees into it would make config.py the place every deployment name
        # has to be declared, which it is not.
        "SONGGEN_ALLOWED_ORIGINS", "SONGGEN_ALLOWED_EMAILS",
        "SONGGEN_GOOGLE_CLIENT_ID", "API_BASE_URL", "GOOGLE_CLIENT_ID",
        # The one real credential in the deployment, and the only reason it is
        # named in a runbook is to say it must be marked secret.
        "AZURE_STATIC_WEB_APPS_API_TOKEN",
    }
    missing = sorted(_referenced_constants(read(ROOT / doc)) - known - allowed)
    assert not missing, f"{doc} names constants that do not exist: {missing}"


def test_glossary_defines_the_load_bearing_terms():
    """These are ordinary words used narrowly; guessing at them misleads."""
    text = read(DOCS / "GLOSSARY.md").lower()
    for term in ("slot", "unit", "phrase", "mimicry", "fold", "ceiling",
                 "climax", "shout", "bank", "candidate"):
        assert f"**{term}**" in text, f"{term!r} is used as a term of art but undefined"


def test_every_review_prefix_is_documented():
    """Getting a prefix wrong risks overwriting hand-reviewed work."""
    glossary = read(DOCS / "GLOSSARY.md")
    for prefix in ("TODO_", "AI_", "SYL_", "EEE_then__", "THEN_"):
        assert prefix in glossary, f"{prefix} is written by the tools but undocumented"


def test_agents_md_states_the_irreversible_rule():
    """The one thing in the repo that cannot be regenerated."""
    text = read(ROOT / "AGENTS.md")
    assert "words/candidates/" in text
    assert "prefix" in text.lower()


def test_readme_does_not_claim_a_stale_build_status():
    """It once said 'Commit 1 of 4' for many commits after that stopped being true."""
    text = read(ROOT / "README.md").lower()
    assert "commit 1 of 4" not in text
    assert "instrumental bed only" not in text


def test_workflows_commands_name_real_modules():
    """A runbook telling you to run a module that does not exist is worse than none."""
    modules = {
        p.stem for p in (ROOT / "src" / "song_generator").glob("*.py")
        if not p.stem.startswith("__") and p.stem not in _LOCAL_ONLY
    }
    invoked = set(re.findall(r"-m song_generator\.(\w+)", read(DOCS / "WORKFLOWS.md")))
    missing = sorted(invoked - modules)
    assert not missing, f"WORKFLOWS.md invokes modules that do not exist: {missing}"


def test_no_assistant_is_credited_as_an_author():
    """Documentation about agents is fine. Crediting one as an author is not.

    The distinction is the point. AGENTS.md and docs/AI-FIRST.md exist to be
    read by agents and are welcome in the repo; what is banned is attribution --
    a trailer, a "generated with" line, a badge. Naming a dependency such as
    openai-whisper is likewise not attribution, it is an install instruction.

    Commit messages are checked separately by hand: a test cannot see them, and
    a trailer already in history is not undone by removing it going forward.
    """
    import re
    import subprocess

    # Assembled from parts so this file does not trip its own check.
    patterns = [
        (r"co-authored-by", "an authorship trailer"),
        (r"generated with", "a generation credit"),
        (r"co-?written (?:by|with)", "an authorship claim"),
        (r"!\[[^\]]*\]\([^)]*(?:cla" + r"ude|anthro" + r"pic)[^)]*\)", "a badge or logo"),
    ]

    exempt = {"CLAUDE.md", "tests/test_docs.py"}  # both must name what they forbid

    tracked = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split()

    offenders = []
    for rel in tracked:
        if rel in exempt:
            continue
        try:
            text = (ROOT / rel).read_text(encoding="utf-8").lower()
        except UnicodeDecodeError:
            # Binary files (wav clips, mp3 renders) cannot carry a prose
            # credit, and undecodable is the only reason to skip one. A
            # tracked file that is MISSING is not skipped: swallowing
            # FileNotFoundError here silently shrank this test's coverage.
            continue
        for pattern, what in patterns:
            if re.search(pattern, text):
                offenders.append(f"{rel} ({what})")

    assert not offenders, "assistant credited as author in: " + ", ".join(offenders)


def test_every_cli_module_can_be_imported():
    """Each runbook entry point must at least load."""
    import importlib

    for name in ("cli", "build_bank", "extract_words", "flatten",
                 "mine_words", "set_aside", "successors", "hunt"):
        module = importlib.import_module(f"song_generator.{name}")
        assert hasattr(module, "main"), f"{name} is documented as runnable but has no main()"


def test_every_command_a_tool_prints_can_actually_be_run():
    """Instructions printed at a user are documentation that ships in the code.

    calculator_low.wav was printed as an example of what to name a clip and
    did not parse, so anyone following it lost that take silently. The same
    shape of mistake applies to a command: a module that was renamed, or a flag
    that never existed, is worse in a printed instruction than in a doc,
    because it arrives at the moment somebody is trying to act on it.
    """
    import importlib
    import re

    text = "".join(p.read_text(encoding="utf-8")
                   for p in (ROOT / "src" / "song_generator").glob("*.py"))
    text += "".join(p.read_text(encoding="utf-8") for p in DOCS.glob("*.md"))

    problems = []
    # The lookahead keeps "song_generator.mp3" out: a name followed by a digit
    # is an output file, not a module, and matching it captured a module "mp"
    # that never existed.
    pattern = r"song_generator\.([a-z_]+)(?![a-z0-9])((?:\s+--[a-z-]+)*)"
    for module, flags in set(re.findall(pattern, text)):
        try:
            loaded = importlib.import_module(f"song_generator.{module}")
        except ImportError:
            problems.append(f"song_generator.{module} does not exist")
            continue
        if not hasattr(loaded, "build_parser"):
            continue
        known = {name for action in loaded.build_parser()._actions
                 for name in action.option_strings}
        for flag in re.findall(r"--[a-z-]+", flags):
            if flag not in known:
                problems.append(f"song_generator.{module} has no {flag}")

    assert not problems, "instructions nobody can follow: " + "; ".join(problems)


def test_a_constant_a_level_overrides_says_so():
    """Four constants stopped governing an ordinary run when the playfulness
    levels started setting their own, and their comments still read as though
    they decided the behaviour. Somebody tuning one would have changed nothing
    and had no way to tell."""
    source = (ROOT / "src" / "song_generator" / "config.py").read_text(encoding="utf-8")

    overridden = {
        "PHRASE_FILL": "phrase_fill",
        "SHOUT_MAX_SHARE": "shout_share",
        "CLIMAX_PHRASE_SHARE": "climax_share",
        "CLIMAX_WILDCARD_CHANCE": "climax_wildcard",
    }
    for constant, knob in overridden.items():
        assert any(knob in level for level in config.PLAY_LEVELS.values()), \
            f"{knob} is claimed as an override and no level sets it"
        before = source.split(f"\n{constant} =")[0]
        recent = before[-700:]
        assert "PLAY_LEVELS" in recent, \
            f"{constant} is overridden by every level and does not say so"


def test_the_readme_describes_both_dials():
    """It described mimicry alone while the tool had grown a second dial.

    Playfulness decides what gets sung and mimicry decides how closely it
    follows the tune. Someone reading only about mimicry would not know the
    other existed, or why a run writes fourteen files rather than seven.
    """
    text = read(ROOT / "README.md").lower()
    assert "mimicry" in text
    assert "playfulness" in text
    assert "conservative" in text and "wild" in text
    assert "fourteen" in text or "14 " in text


def test_a_test_count_in_the_docs_matches_the_suite():
    """The one claim in these docs that rots on its own.

    Every other statement here goes stale only when somebody changes
    behaviour. A test count goes stale when somebody adds a test, which is the
    thing this repo most wants to encourage, so it drifted three times in a
    single day: 192, then 419, then 467, each correction obsolete before it
    was merged.

    So the count lives in exactly one place and is checked. Anything else that
    wants to mention the suite says how long it takes, which does not move.

    Collected rather than run, so this stays cheap. The inner pytest does not
    execute anything and cannot recurse into running this file.
    """
    import re
    import subprocess
    import sys

    prose = ["AGENTS.md", "README.md", "docs/GLOSSARY.md",
             "docs/ARCHITECTURE.md", "docs/WORKFLOWS.md",
             "docs/DATA-FORMATS.md", "docs/TODO.md", "docs/AI-FIRST.md"]
    claims = []
    for name in prose:
        if name == "docs/AI-FIRST.md":
            # An iteration log. Its counts are snapshots of what was true at
            # each step, so correcting them to today's number would falsify
            # the record rather than fix it.
            continue
        for line in read(ROOT / name).splitlines():
            for match in re.finditer(r"\b(\d+) tests\b", line):
                claims.append((name, int(match.group(1)), line.strip()))

    assert len(claims) <= 1, (
        "a test count belongs in one place, and these each have to be edited "
        f"whenever anyone adds a test: {[(n, c) for n, c, _ in claims]}"
    )
    if not claims:
        return

    out = subprocess.run(
        [sys.executable, "-m", "pytest", str(ROOT / "tests"), "-q", "--collect-only"],
        capture_output=True, text=True, cwd=ROOT,
    ).stdout
    found = re.search(r"(\d+) tests? collected", out)
    assert found, f"could not read a collected count from pytest:\n{out[-500:]}"

    path, claimed, line = claims[0]
    assert claimed == int(found.group(1)), (
        f"{path} says {claimed} tests, the suite collects {found.group(1)}.\n"
        f"    {line}"
    )
