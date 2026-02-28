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

## Custom Adapters Quickstart
Create a minimal custom adapter end-to-end using `httpbin.org` (global, simple, auth-friendly test target).

1. Create adapter directory:
```bash
mkdir -p ~/.web2cli/adapters/httpbin.org
```

2. Create `~/.web2cli/adapters/httpbin.org/web2cli.yaml`:
```yaml
meta:
  spec_version: "0.2"
  name: httpbin
  domain: httpbin.org
  base_url: https://httpbin.org
  version: 0.2.0
  description: "HTTPBin demo adapter"
  author: custom
  aliases: [hb]
  transport: http
  impersonate: chrome
  default_headers:
    Accept: "application/json"

auth:
  methods:
    - type: token
      env_var: WEB2CLI_HTTPBIN_TOKEN
      inject:
        target: header
        key: Authorization
        prefix: "Bearer "
    - type: cookies
      keys: [session]
      env_var: WEB2CLI_HTTPBIN_COOKIES

commands:
  ip:
    description: "Show IP seen by server"
    pipeline:
      - request:
          name: fetch
          method: GET
          url: /ip
      - parse:
          name: parsed
          from: fetch
          format: json
          extract: "$"
          fields:
            - name: origin
              from: "$.origin"
    output:
      from_step: parsed
      default_fields: [origin]
      default_format: table

  bearer-check:
    description: "Check bearer auth"
    pipeline:
      - request:
          name: fetch
          method: GET
          url: /bearer
      - parse:
          name: parsed
          from: fetch
          format: json
          extract: "$"
          fields:
            - name: authenticated
              from: "$.authenticated"
              default: false
            - name: token
              from: "$.token"
              default: ""
    output:
      from_step: parsed
      default_fields: [authenticated, token]
      default_format: table

  cookies:
    description: "Echo cookies seen by server"
    pipeline:
      - request:
          name: fetch
          method: GET
          url: /cookies
      - parse:
          name: parsed
          from: fetch
          format: json
          extract: "$.cookies"
    output:
      from_step: parsed
      default_format: json
```

3. Validate and lint:
```bash
web2cli adapters validate
web2cli adapters lint httpbin.org
```

4. Inspect and run:
```bash
web2cli adapters info hb
web2cli hb ip
```

5. Test token auth (session-based):
```bash
web2cli login hb --token "abc123"
web2cli hb bearer-check --trace --verbose
```

6. Test cookie auth:
```bash
web2cli login hb --cookies "session=my-session"
web2cli hb cookies --format json
```

If you prefer env vars instead of stored sessions:
```bash
export WEB2CLI_HTTPBIN_TOKEN="abc123"
export WEB2CLI_HTTPBIN_COOKIES="session=my-session"
web2cli hb bearer-check
web2cli hb cookies
```

## Built-in Adapters
Current built-in adapters and actions:

### discord.com (`dc`, `discord`)
- `me` - Show current user info
- `servers` - List your Discord servers (guilds)
- `channels` - List channels in a server
- `messages` - Get messages from a channel
- `send` - Send a message to a channel
- `dm` - List DM conversations
- `dm-messages` - Get messages from a DM conversation
- `dm-send` - Send a DM to a user

### news.ycombinator.com (`hn`)
- `top` - Get top stories from Hacker News
- `new` - Get newest stories
- `item` - Get a single HN item (story, comment, job)
- `search` - Search HN stories (via Algolia)
- `saved` - Get saved stories (requires login)
- `upvoted` - Get upvoted stories (requires login)
- `submissions` - Get a user's submissions

### reddit.com (`reddit`)
- `posts` - List posts from a subreddit
- `thread` - Get a thread with comments
- `search` - Search posts in a subreddit

### slack.com (`slack`)
- `me` - Show current user and workspace info
- `channels` - List channels in workspace
- `messages` - Get messages from a channel
- `send` - Send a message to a channel
- `dm` - List DM conversations
- `dm-messages` - Get messages from a DM conversation
- `dm-send` - Send a DM to a user

### stackoverflow.com (`so`)
- `search` - Search Stack Overflow questions
- `question` - Read a specific question and its top answers
- `tagged` - Browse questions by tag

### x.com (`x`, `twitter`)
- `tweet` - Get a single tweet by ID or URL
- `profile` - Get user profile info
- `search` - Search tweets
- `timeline` - Home timeline (For you tab)
- `following` - Following timeline

To inspect adapter details from CLI:

```bash
web2cli adapters list
web2cli adapters info <domain-or-alias>
```

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

