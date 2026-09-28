# Pull request authoring contract

Everything about the body's shape — the template, the section order, which visual to
pick for Summary, how to word Merge Danger — belongs to the installed `pr` skill. This
file holds only what Cognovis adds on top of it.

## Resolve the installed `pr` skill

Read its `SKILL.md` from the first root that exists, project-local before global:

```text
<repo>/.agents/skills/pr   <repo>/.claude/skills/pr
~/.agents/skills/pr        ~/.claude/skills/pr
```

Use its live template as it stands; it is the single source for the body. If no root
has it, report that setup failure instead of writing a template from memory.

## Title

Line one of the file, at most 120 characters, naming the observable result rather than
the activity. `Reduce the Praxis IG to two extensions and eight code systems` beats
`Refactor IG`.

## Sections Cognovis adds

Append these after the sections the `pr` skill defines. This is the single list of
what a Cognovis delivery adds to the upstream template; a calling skill supplies the
content and does not keep its own copy of the list.

### Work order reference

`Closes #<n>` when the issue lives in the same repository, the full issue URL
otherwise.

### Review decisions

Rendered by `finding_triage.py --review-decisions`: the local review findings that were
deferred, and the ones the repair commit fixed. Take its output as given rather than
restating the findings.

### Verification

The verdict from the delivery's non-author verifier, the head SHA it verified, and each
run path with its observed result. A new commit on the branch invalidates the verdict.
`executive-pack` owns both this section's content and the verifier; do not produce a
verdict here.

### Reviewer routes

The model route each of the delivery's three reviewers actually used, as reported by
the delivery. Record a fallback route as the route; do not present an alias that was
unavailable.

### Known residuals

What the reviewer must still know: remaining risk, external configuration, a staged
rollout, intentionally excluded behaviour. Write `None known` when empty.

## Evidence that is not text

For a user-visible surface, the verification walkthrough (Playwright, CLI, or a scripted
check) captures what the user now sees. Attach it only when such a surface changed; a
change with no visual surface needs no screenshot.

1. Capture the headline frames, before and after where possible, into a scratch location
   outside the worktree.
2. Screen each one for secret values, customer data, prompts or pilot identifiers.
   Recapture or omit, and record the omission in the body.
3. Attach after the pull request exists. On GitHub, `gh pr edit <n> --attach
   './shot.png#alt text'` or the same flag on `gh pr comment`. On Forgejo, `POST` each
   file to `/api/v1/repos/{owner}/{repo}/issues/{index}/assets` with the multipart field
   `attachment` and embed the returned `browser_download_url`.
4. Authorize from the environment or existing ccore credential state; never on the
   command line, never in the body.
5. Never commit, diff or store this evidence inside the repository.

## Language

The `writing/unslop` and `writing/plain-technical-english` standards apply to the
finished text; they are not repeated here.

## Handoff to ccore

Write the file outside the worktree, for example `/tmp/pr-<branch>.md`, and pass its
full content as the summary:

```bash
ccore pr ensure --repo <worktree> --summary "$(cat /tmp/pr-<branch>.md)"
```

ccore takes line one as the title, truncated at 120 characters, keeps the whole text as
the body, picks `gh` or `fgj` from the remote, and appends the identity footer with
harness, session and work-order references. Do not write that footer yourself. It
rebases onto the target before its first push; when that moves the head commit, the
Verification section needs a fresh verdict. Push later commits with a plain `git push`.
The merge decision stays with the `executive-pack` delivery.
