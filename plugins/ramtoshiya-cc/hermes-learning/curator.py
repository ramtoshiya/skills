"""Run Hermes's curator when its interval has passed. Runs under the Hermes interpreter with HERMES_HOME set to
the store. No Hermes agent runs for the learning store, so nothing else would. The scheduled pass makes no model
calls: it moves skills nobody used to stale and then to the archive."""

from agent.curator import maybe_run_curator

maybe_run_curator()
