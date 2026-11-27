# Process

These rules apply to all work in this repository and load in every Claude Code session. Each rule links the owner decisions it comes from. The other pages in this folder hold the rules for one part of the code each, and start with `paths:` frontmatter that names the files they govern.

- Keep tool defaults, model lists and worker routing within what the current
  subscriptions include. Prefer a setup that follows the account by itself, such
  as a model list filtered in one place or a quota reading, over model names
  fixed in several places. ([Setups fit the current subscription
  tier](../../docs/decisions/2026-11-27-fit-setups-to-current-subscription-tier.md))
