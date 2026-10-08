# ne-observability

Local observability for every profile on a [Hermes Agent](https://github.com/NousResearch/hermes-agent) install. Adds an **Observability** page to Hermes Desktop and an `/obs [days]` slash command.

What it shows, per profile or across the whole instance:

- **Tokens, calls and reported cost**, split into main-model and auxiliary-model usage
- **Models** used, with input, output and cache-read tokens
- **Crons**: LLM usage per scheduled job (runs, tokens, tokens per run, models, last run)
- **Aux tasks**: which auxiliary tasks (titling, compression, and so on) cost the most
- **Skills triggered**, **subagents** spawned, and **permission issues** (denied or timed-out approvals, blocked tools, provider 401/403 errors)

Filters: time range (1/7/30/90 days), profile, and **Kanban board**.

## Install

```bash
hermes plugins install nacke81/hermes-ne-observability
```

Restart Hermes Desktop, then open **Observability** in the sidebar. In any chat, `/obs 7` prints a markdown summary of the last 7 days.

## How it works

- **Tokens, models, cost and crons** are read directly from each profile's `state.db`, so you get full history from day one.
- **Skills, subagents, approvals and permission issues** come from plugin hooks. They are recorded from the day you install the plugin.
- **Board filter**: Hermes doesn't tag sessions with a Kanban board, so the plugin matches each Kanban worker session to a board's task runs by profile and start time. Subagents inherit their parent's board. Expect about 99% coverage; when runs overlap, the most recent one wins. Crons belong to no board.
- **Cost** is whatever your providers report. Subscription and some OpenAI-compatible providers report nothing, so cost shows $0.

## Privacy

Nothing leaves your machine. Hook events are metadata only (names, statuses, token counts, short redacted error snippets), written to `<hermes root>/plugin-data/ne-observability/events.db`. Events older than 180 days are pruned. No API keys or network calls.

## Compatibility

Requires Hermes >= 0.21. The plugin reads Hermes's internal SQLite schemas (`state.db`, `kanban.db`). A Hermes update that changes those schemas can break a section until the plugin is updated. Please open an issue if that happens.

## License

MIT
