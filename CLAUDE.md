# Agent guide

The working guidance lives in **[AGENTS.md](AGENTS.md)**, how to run things,
what must never be touched, where the traps are, and the reading order. This
file exists because agents look for this name; the content is not duplicated.

Read [AGENTS.md](AGENTS.md) first.

## Project rules for attribution

Documentation about working with agents is welcome in this repo, that is what
`AGENTS.md` and `docs/AI-FIRST.md` are for. **Crediting an assistant as an
author is not.**

- **No `Co-Authored-By:` trailer on any commit**: for any assistant. The habit
  of adding one does not apply here. The 26 commits that had one were rewritten
  to remove it.
- **No "Generated with …" lines** in commit bodies, pull requests or issues.
- **No badges, logos or attribution lines** in the README or anywhere else.
- The author of every commit is the person who owns the repo.

### Anything written outward-facing

Pull request titles and bodies, issue text, release notes, changelog entries and
review comments are all written **in the project's own voice**. They describe
what changed and why, and nothing else.

They never mention an assistant, never mention that AI was involved, never carry
a generation footer, and never credit a co-author. A default habit of appending
one does not apply in this repo, and this rule outranks it.

The distinction that makes this consistent with the rest of the repo: files may
freely discuss working with agents, because someone has to open them and it is
useful once they do. Anything presented *at* a reader is different. A landing
page, a pull request description or a commit subject is the project speaking,
and the project is not an assistant.

`tests/test_docs.py` enforces the first three in any tracked file. It cannot see
commit messages, so before a push:

```powershell
git log --all --pretty=format:'%B' | Select-String -Pattern 'Co-Authored-By|Generated with'
```

That must return nothing.
