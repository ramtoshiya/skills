# Select a release from current evidence


Establish the action's official GitHub repository from its publisher's documentation
and repository identity. Do not replace it with a fork, similarly named action, or
Marketplace search result. Query its releases during this task. For example, with
`repo` set to the verified `owner/repo`:

```sh
gh api --paginate "repos/$repo/releases?per_page=100" \
  --jq '.[] | {tag_name, published_at, draft, prerelease, html_url, body}'
```

Follow pagination. Do not use only `/releases/latest` or assume API order, tag name,
commit date, or a major alias proves release recency. Record the lookup time in UTC.
A qualifying release has `draft == false`, `prerelease == false`, a stable version,
and a verified `published_at` at least 72 hours before that lookup time:

```text
lookup_time_utc - published_at_utc >= 259200 seconds
```

Compare full timestamps, not calendar dates. A release exactly 72 hours old qualifies,
one a second younger does not. Exclude future or missing publication timestamps and
versions labeled alpha, beta, rc, nightly, or otherwise unstable even if incorrectly
marked stable. Do not use a tag's commit timestamp as its publication time.

Choose the newest compatible stable release among those that qualify. Compare
versions using the publisher's version scheme, not lexical sorting, and explain
any newer eligible release rejected for incompatibility. Review release notes and
migration guidance for the selected release and intervening releases since the
existing pin. Do not silently stay on an old major or assume a major bump is safe.

If the newest release is too young, consider the newest older eligible release.
Do not waive, bypass, or shorten the cooldown, even for urgency or a security fix.
If no safe compatible eligible release exists, stop and report the blocker and
when the candidate would become eligible. If official lookup, tag provenance, or
release age cannot be verified, stop before editing and report the missing evidence.
No releases, rate limits, authentication errors, and offline access are blockers,
not permission to invent a version, SHA, or publication date.

