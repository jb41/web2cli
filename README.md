# web2cli

**Every website is a Unix command.**

Browse Hacker News, search X.com, write Discord messages, read Reddit — all from your terminal. No browser, no API keys, no $100/mo plans.

```bash
$ web2cli hn top --limit 3
┌──────┬──────────────────────────────────────────┬───────┬──────────┐
│ RANK │ TITLE                                    │ SCORE │ COMMENTS │
├──────┼──────────────────────────────────────────┼───────┼──────────┤
│ 1    │ Show HN: I built a CLI for every website │ 313   │ 37       │
│ 2    │ Why agents don't need browsers           │ 271   │ 89       │
│ 3    │ The Unix philosophy, 50 years later      │ 198   │ 64       │
└──────┴──────────────────────────────────────────┴───────┴──────────┘
```

```bash
$ web2cli x search --query "build for agents" --limit 1 --format json
[
  {
    "author": "@karpathy",
    "text": "CLIs are super exciting precisely because they are a \"legacy\" technology, which means AI agents can natively and easily use them, combine them, interact with them via the entire terminal toolkit.\n\nE.g ask your Claude/Codex agent to install this new Polymarket CLI and ask for any https://t.co/gzrpg0erGz",
    "date": "2026-02-24 18:17",
    "retweets": 1085,
    "likes": 11481,
    "replies": 610,
    "views": "1923316"
  }
]
```

```bash
$ web2cli discord send --server "My Server" --channel general --message "deployed 🚀" > /dev/null
```

## Why?
- **For agents**: HTTP GET, not Chromium. 50ms not 5s. \$0.000001 not \$0.10.
- **For humans**: `curl` for the modern web. Pipe, grep, script anything.
- **For both**: One interface. `web2cli <site> <command>`. That's it.

## Documentation
Key docs for contributors:

- `docs/adapter-spec.md` - canonical adapter specification (current: `0.2`)
- `docs/llm-adapter-playbook.md` - adapter authoring workflow for LLM agents
- `docs/adapter-spec.schema.json` - machine-readable schema for quick structural checks

## Debugging and Quality

```bash
# Validate + semantic lint all adapters
web2cli adapters validate
web2cli adapters lint

# Inspect step-by-step runtime trace for a command
web2cli reddit posts --sub python --limit 3 --trace
```

## For LLMs
If you are using an LLM/agent to generate a new adapter, use this flow:

1. Start from `docs/llm-adapter-playbook.md` and the minimal adapter template.
2. Prefer declarative steps (`resolve`, `request`, `fanout`, `parse`, `transform`).
3. Avoid custom parser scripts unless declarative parsing is truly insufficient.
4. Always run:
   - `web2cli adapters validate`
   - `web2cli adapters lint`
   - at least one command with `--trace`
5. Do not stop until all three checks pass and output fields look correct.

