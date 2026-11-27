## Owner decisions

`docs/decisions/` holds one record per decision that the owner made, with the owner's words and the situation they were said in. `docs/decisions/README.md` says how to record one. Only the owner makes or changes a decision. Never cite your own or another agent's ruling as the owner's.

The current rules are in topic pages under `.claude/rules/`. Each rule links to the records it comes from. Claude Code loads `process.md` in every session and a topic page when you work on the files its `paths:` names. Other agents read the pages of their work's topics. When a page and a record disagree, the record wins, and the page needs fixing. `python3 tools/decisions/decisions.py list` lists the active decisions, and `python3 tools/decisions/decisions.py check` checks records, links and citations.

Topic pages:

- [process](.claude/rules/process.md): rules for all work.
