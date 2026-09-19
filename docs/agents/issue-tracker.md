# Issue tracker: GitHub

Issues and specs for this repo live as GitHub issues. Use the `gh-personal`
wrapper for all operations so commands always authenticate as `JohnMansell`
without changing the active account in `~/.config/gh/hosts.yml`.

## Conventions

- **Create an issue**: `gh-personal issue create --title "..." --body "..."`. Use a heredoc for multi-line bodies.
- **Read an issue**: `gh-personal issue view <number> --comments`, filtering comments by `jq` and also fetching labels.
- **List issues**: `gh-personal issue list --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'` with appropriate `--label` and `--state` filters.
- **Comment on an issue**: `gh-personal issue comment <number> --body "..."`
- **Apply / remove labels**: `gh-personal issue edit <number> --add-label "..."` / `--remove-label "..."`
- **Close**: `gh-personal issue close <number> --comment "..."`

Infer the repo from `git remote -v`. If the SSH host alias prevents automatic
inference, pass `--repo JohnMansell/CraigsListScrape` explicitly.

## Pull requests as a triage surface

**PRs as a request surface: no.** _(Set to `yes` if this repo treats external PRs as feature requests; `/triage` reads this flag.)_

When set to `yes`, PRs run through the same labels and states as issues, using the `gh-personal pr` equivalents:

- **Read a PR**: `gh-personal pr view <number> --comments` and `gh-personal pr diff <number>` for the diff.
- **List external PRs for triage**: `gh-personal pr list --state open --json number,title,body,labels,author,authorAssociation,comments` then keep only `authorAssociation` of `CONTRIBUTOR`, `FIRST_TIME_CONTRIBUTOR`, or `NONE` (drop `OWNER`/`MEMBER`/`COLLABORATOR`).
- **Comment / label / close**: `gh-personal pr comment`, `gh-personal pr edit --add-label`/`--remove-label`, `gh-personal pr close`.

GitHub shares one number space across issues and PRs, so a bare `#42` may be either. Resolve with `gh-personal pr view 42` and fall back to `gh-personal issue view 42`.

## When a skill says "publish to the issue tracker"

Create a GitHub issue with `gh-personal`.

## When a skill says "fetch the relevant ticket"

Run `gh-personal issue view <number> --comments`.

## Wayfinding operations

Used by `/wayfinder`. The **map** is a single issue with **child** issues as tickets.

- **Map**: a single issue labelled `wayfinder:map`, holding the Notes / Decisions-so-far / Fog body. `gh-personal issue create --label wayfinder:map`.
- **Child ticket**: an issue linked to the map as a GitHub sub-issue (`gh-personal api` on the sub-issues endpoint). Where sub-issues aren't enabled, add the child to a task list in the map body and put `Part of #<map>` at the top of the child body. Labels: `wayfinder:<type>` (`research`/`prototype`/`grilling`/`task`). Once claimed, the ticket is assigned to the driving dev.
- **Blocking**: GitHub's **native issue dependencies**, the canonical, UI-visible representation. Add an edge with `gh-personal api --method POST repos/<owner>/<repo>/issues/<child>/dependencies/blocked_by -F issue_id=<blocker-db-id>`, where `<blocker-db-id>` is the blocker's numeric **database id** (`gh-personal api repos/<owner>/<repo>/issues/<n> --jq .id`, _not_ the `#number` or `node_id`). GitHub reports `issue_dependencies_summary.blocked_by` (open blockers only; this is the live gate). Where dependencies aren't available, fall back to a `Blocked by: #<n>, #<n>` line at the top of the child body. A ticket is unblocked when every blocker is closed.
- **Frontier query**: list the map's open children (`gh-personal issue list --state open`, scoped to the map's sub-issues / task list), drop any with an open blocker (`issue_dependencies_summary.blocked_by > 0`, or an open issue in the `Blocked by` line) or an assignee; first in map order wins.
- **Claim**: `gh-personal issue edit <n> --add-assignee @me`. This is the session's first write.
- **Resolve**: `gh-personal issue comment <n> --body "<answer>"`, then `gh-personal issue close <n>`, then append a context pointer (gist + link) to the map's Decisions-so-far.
