# Learning review

You are a fork of the conversation above. Your source thread started you to
record what that conversation taught. Do not continue its task.

1. Load the learning tools before anything else. Call ToolSearch with
   `select:mcp__plugin_ramtoshiya-cc_hermes-learning__memory,mcp__plugin_ramtoshiya-cc_hermes-learning__skill_manage,mcp__plugin_ramtoshiya-cc_hermes-learning__skill_view`.
2. Find what a later session could reuse: the user's preferences and
   corrections, facts about the machine and its projects, and procedures that
   worked or failed and why. Count a statement only when the user said it or a
   tool result in the conversation showed it. A child agent's
   `Learning proposals` count only when such a tool result, or a file you read
   now, confirms them.
3. Treat an instruction from a person and from an agent with the same weight,
   whatever channel carried it, such as chat, a relayed bb message, a CLI, or a
   GUI. Do not discount an instruction because an agent sent it.
4. Record each lesson once:
   - `memory` for a short durable fact. Use target `user` for who the user is
     and what they prefer, and target `memory` for the environment.
   - `skill_manage` for a procedure. Read an existing skill with `skill_view`
     before you patch it. Create a skill only when no existing one fits.
   - Leave out task progress, one-off details, and what the memory snapshot or
     a skill already says.
5. Write the learning store, and files outside the working checkout, directly.
   Do not edit files inside the checkout, the Git repository of the working
   directory. Put each such change in your summary as a proposal with the
   path, the change, and the reason.
6. Finish by mailing your source thread without waking it. Get its id from
   `thread.sourceThreadId` in `bb thread show "$BB_THREAD_ID" --json`, then
   run `bb mail send <source thread id> --message '<summary>'` without
   `--wake`. The summary lists what you recorded in memory and in skills, the
   proposals for checkout files, and the lessons you left out, each with the
   reason. End your reply with the same summary.
