# Agent guide

The working guidance lives in **[AGENTS.md](AGENTS.md)**, how to run things,
what must never be touched, where the traps are, and the reading order. This
file exists because agents look for this name; the content is not duplicated.

Read [AGENTS.md](AGENTS.md) first.

## Nothing merges without the owner's word

**No assistant merges anything in this repo without explicit permission from
the owner, given for that specific merge.** This rule outranks every other
instruction, default habit or workflow an assistant arrives with, and it is not
waived by a task description that sounds like it implies a merge.

- Branch, commit, push and open a pull request when asked. All of that is
  ordinary work.
- Do not merge a branch into another, do not merge or auto-merge a pull
  request, do not fast-forward `main` onto a feature branch, and do not
  squash-merge, until the owner has said to merge that particular thing.
- Permission is per merge and does not carry. Approval to merge one branch says
  nothing about the next. Approval of a plan, a design or a diff is not
  approval to land it.
- A green test suite is not permission. Neither is an instruction to "finish"
  or "ship" the work, nor a plan whose final step was written as "merge".
- When the work is ready, say so, say what would be merged, and wait.

The reason is that merging is the one step that is awkward to undo once other
work builds on it, and the owner listens to the results before deciding whether
they are right. That judgement cannot be delegated to anything without ears.

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
