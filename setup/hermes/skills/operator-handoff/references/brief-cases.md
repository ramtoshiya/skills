# Brief cases {:#brief-cases}

Add these to the brief described in Write the brief in `SKILL.md` when the case
applies.

## No remote {:#no-remote}

When `git remote -v` in the owning repository prints nothing, replace "commit,
and push" in the authority paragraph with "commit, and merge into the local
`main`" and keep the rest verbatim.

## Forked skill {:#forked-skill}

When the skill comes from a fork listed in
`{{SKILLS_REPO}}/.github/upstream-forks.json`, check whether its upstream has
commits the fork lacks, with
`gh api 'repos/<upstream>/compare/<upstreamBranch>...<fork owner>:<branch>'`,
and whether those commits change what the diff targets. If they do, say so in
the brief and to the user, who decides whether the fork syncs first.

## Web UI or server {:#web-ui}

When the work delivers a web UI or server that the user will open, the
expected result says that it keeps running after the worker finishes, how to
restart it, and that it opens from another of the user's devices.

## Independent pieces {:#independent-pieces}

When the work splits into pieces that each stand on their own, the expected
result says to integrate each piece once it passes the checks, as the
authority paragraph describes, instead of holding all of it for one final
integration. Say the same when a later message adds scope to a running
worker. A brief that integrates only at the end keeps finished work off
`main` and can leave the user wondering why integration is delayed.
