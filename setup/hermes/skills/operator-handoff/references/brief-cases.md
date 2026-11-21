# Brief cases {:#brief-cases}

Add these to the brief described in Write the brief in `SKILL.md` when the case
applies.

## No remote {:#no-remote}

When `git remote -v` in the owning repository prints nothing, replace "commit,
and push" in the authority paragraph with "commit, and merge into the local
`main`" and keep the rest verbatim.

## Forked skill {:#forked-skill}

When the skill comes from a fork, its entry in
`{{SKILLS_REPO}}/dev/automation/upstream-updates/upstreams.json` names the
branch that the pin uses. The brief names that branch and says to change it
only with new commits or merges, never a rebase or force-push. A daily update
agent merges upstream into the same branch and needs every pin to stay on it.

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
