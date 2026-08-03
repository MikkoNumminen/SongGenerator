"""Keep the documentation honest.

Docs rot silently, and an agent trusting a stale instruction is worse off than
one with no docs at all -- it will confidently run the wrong command. These
tests fail when the documentation and the code disagree, so drift becomes a red
test rather than someone's wasted afternoon.
"""

import re
from pathlib import Path

import pytest

from luokkaretki_generator import config

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("name", [
    "CLAUDE.md",
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
        p.stem for p in (ROOT / "src" / "luokkaretki_generator").glob("*.py")
        if not p.stem.startswith("__")
    }
    described = read(DOCS / "ARCHITECTURE.md")
    missing = sorted(m for m in modules if f"{m}.py" not in described)
    assert not missing, f"undocumented modules: {missing}"


def test_architecture_map_lists_no_module_that_was_deleted():
    modules = {p.stem for p in (ROOT / "src" / "luokkaretki_generator").glob("*.py")}
    described = set(re.findall(r"`(\w+)\.py`", read(DOCS / "ARCHITECTURE.md")))
    stale = sorted(described - modules)
    assert not stale, f"documented but gone: {stale}"


def _referenced_constants(text: str) -> set[str]:
    """SCREAMING_CASE names a doc claims exist in config.

    Example filenames are excluded: an uppercase name ending in a digit is
    something like PASKA3.wav, not a constant.
    """
    return {
        name for name in re.findall(r"\b([A-Z][A-Z0-9_]{4,})\b", text)
        if not name.startswith(("TODO", "NOTE", "MODE", "SYL", "THEN", "EEE", "AI"))
        and not name[-1].isdigit()
    }


@pytest.mark.parametrize("doc", [
    "CLAUDE.md", "README.md",
    "docs/WORKFLOWS.md", "docs/GLOSSARY.md",
    "docs/ARCHITECTURE.md", "docs/DATA-FORMATS.md",
])
def test_constants_named_in_docs_actually_exist(doc):
    """Naming a constant that was renamed sends a reader hunting for nothing."""
    known = set(dir(config))
    # Words that look like constants but are prose or JSON keys.
    allowed = {
        "CLAUDE", "README", "GLOSSARY", "ARCHITECTURE", "WORKFLOWS",
        "DEMUCS", "WORLD", "PATH", "JSON", "LUFS", "PYTHONPATH", "GPU",
        "NVIDIA", "TSV", "BOM", "DENSITY", "CLIMAXES", "STAGE", "LISTEN",
        "FIRST", "FORMATS", "PASKA", "OTHER",
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


def test_claude_md_states_the_irreversible_rule():
    """The one thing in the repo that cannot be regenerated."""
    text = read(ROOT / "CLAUDE.md")
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
        p.stem for p in (ROOT / "src" / "luokkaretki_generator").glob("*.py")
        if not p.stem.startswith("__")
    }
    invoked = set(re.findall(r"-m luokkaretki_generator\.(\w+)", read(DOCS / "WORKFLOWS.md")))
    missing = sorted(invoked - modules)
    assert not missing, f"WORKFLOWS.md invokes modules that do not exist: {missing}"


def test_every_cli_module_can_be_imported():
    """Each runbook entry point must at least load."""
    import importlib

    for name in ("cli", "build_bank", "extract_words", "flatten",
                 "mine_words", "set_aside", "successors", "hunt"):
        module = importlib.import_module(f"luokkaretki_generator.{name}")
        assert hasattr(module, "main"), f"{name} is documented as runnable but has no main()"
