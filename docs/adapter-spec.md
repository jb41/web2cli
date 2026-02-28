# web2cli Adapter Specification

> Every website is a command.

---

Current spec version: `0.2`

---

## Philosophy

Spec `0.2` moves behavior from adapter-local Python scripts into declarative YAML.

Main principles:

1. Pipeline-based command execution (`resolve -> request -> fanout -> parse -> transform`)
2. Reusable named resources (with cache + optional pagination)
3. Explicit body encodings (`json`, `form`, `text`, `bytes`)
4. Auth injection and browser-capture policy in adapter spec
5. Provider plugins for protocol-heavy sites (e.g. `x_graphql`)

Custom Python is still an escape hatch, not the default.

---

## Normative Language

The keywords `MUST`, `SHOULD`, and `MAY` in this document are normative:

- `MUST`: required for compliance.
- `SHOULD`: strongly recommended unless there is a clear reason not to.
- `MAY`: optional behavior.

---

## LLM Authoring Rules

These rules are optimized for agent-generated adapters.

`MUST`:

- Generate adapters that are fully declarative YAML by default.
- Define explicit step names for non-trivial pipelines (especially when referenced by `from` or templates).
- Keep `output.from_step` aligned with the final intended record-producing step.
- Run `web2cli adapters validate` and `web2cli adapters lint` after generating changes.
- Run at least one real command using `--trace` during debugging.

`SHOULD`:

- Reuse `resources` for repeated name -> id lookups.
- Keep field names stable and user-facing (`author`, `text`, `date`, `url`, etc.).
- Prefer built-in ops/transforms over custom parser scripts.
- Use `coalesce` when upstream payloads are known to vary by shape.

`SHOULD NOT`:

- Add custom parser scripts for simple flatten/filter/map operations.
- Encode long business logic in templates.
- Duplicate identical parse blocks across commands when shared resources/steps can be used.

Related docs:

- `docs/llm-adapter-playbook.md`
- `docs/adapter-spec.schema.json`

---

## File Structure

```text
~/.web2cli/adapters/<domain>/
├── web2cli.yaml
└── parsers/            # optional custom parser escape hatch
```

---

## Top-level Schema

```yaml
meta:
auth:
resources:
commands:
```

Machine-readable schema:

- `docs/adapter-spec.schema.json`

---

## Minimal Complete Adapter

Smallest practical adapter/command:

```yaml
meta:
  spec_version: "0.2"
  name: example
  domain: example.com
  base_url: https://api.example.com
  version: 0.2.0
  description: "Example adapter"
  author: web2cli-core

commands:
  ping:
    description: "Ping endpoint"
    pipeline:
      - request:
          name: fetch
          method: GET
          url: /ping
      - parse:
          name: parsed
          from: fetch
          format: json
          extract: "$"
    output:
      from_step: parsed
      default_format: json
```

This example is valid because:

- `meta.spec_version` is `0.2`.
- command defines `pipeline`.
- output points to an existing step.

---

## 1. `meta`

```yaml
meta:
  spec_version: "0.2"
  name: slack
  domain: slack.com
  base_url: https://slack.com/api
  version: 0.2.0
  description: "Slack — channels, messages, DMs"
  author: web2cli-core
  transport: http
  impersonate: chrome
  aliases: [slack]
  default_headers:
    User-Agent: "Mozilla/5.0 ..."
    Accept: "application/json"
```

Required:

- `spec_version`, `name`, `domain`, `base_url`

---

## 2. `auth`

```yaml
auth:
  methods:
    - type: cookies
      keys: [d]
      env_var: WEB2CLI_SLACK_COOKIES

    - type: token
      env_var: WEB2CLI_SLACK_TOKEN
      inject:
        target: form      # header | query | form | cookie
        key: token
        prefix: ""        # optional
      capture:
        from: request.form    # request.header | request.form
        key: token
        match:
          host: slack.com
          path_regex: "^/api/"
          method: POST        # optional
        strip_prefix: ""      # optional
```

Notes:

- Multiple methods can be combined (e.g. cookies + token from env vars).
- `inject` controls where auth value is written into the request.
- If no `inject` is given for token auth, runtime defaults to `Authorization` header.
- `capture` is used by `web2cli login <domain> --browser` to extract token values
  from browser network requests.
- `capture.from: request.header` reads request headers, `request.form` reads form bodies
  (`application/x-www-form-urlencoded` and `multipart/form-data`).
- If multiple token `capture` rules are declared, runtime uses the first rule (in method order)
  that yields a non-empty value.
- Browser login succeeds only after all required cookie keys and configured token capture
  values are collected.

---

## 3. `resources`

Resources are reusable lookup datasets (typically name -> id).

```yaml
resources:
  channels:
    cache:
      key: channels
      ttl: 300
    request:
      method: POST
      url: /conversations.list
      body:
        encoding: form
        template:
          types: public_channel,private_channel
          limit: 200
    paginate:
      cursor_param: cursor
      cursor_location: body   # params | body
      cursor_path: "$.response_metadata.next_cursor"
    response:
      format: json
      extract: "$.channels[*]"
      fields:
        - name: id
          from: "$.id"
        - name: name
          from: "$.name"
```

`resolve` steps use these resources for argument-to-id mapping.

---

## 4. `commands`

Each command defines:

- `args`
- `pipeline`
- `output`

```yaml
commands:
  messages:
    description: "Get messages from a channel"
    args:
      channel:
        type: string
        required: true
      limit:
        type: int
        default: 20
    pipeline:
      - resolve:
          name: channel
          resource: channels
          input: "{{args.channel}}"
          by: name
          value: id
          match: ci_equals
      - request:
          name: fetch
          method: POST
          url: /conversations.history
          body:
            encoding: form
            template:
              channel: "{{steps.channel.id}}"
              limit: "{{args.limit}}"
      - parse:
          name: parsed
          from: fetch
          format: json
          extract: "$.messages[*]"
          fields:
            - name: author
              from: "$.user"
            - name: text
              from: "$.text"
          post_ops:
            - reverse
    output:
      from_step: parsed
      default_fields: [author, text]
      default_format: table
```

---

## 5. `args`

Supported types:

- `string`
- `int`
- `float`
- `bool`
- `flag`
- `string[]`

`source`:

- `arg`
- `stdin`

Only one arg per command may include `stdin`.

---

## 6. Pipeline Step Types

## 6.1 `resolve`

```yaml
- resolve:
    name: channel
    resource: channels
    input: "{{args.channel}}"
    by: name
    value: id
    match: ci_equals     # equals | ci_equals | contains
```

Outputs in context:

- `steps.<name>.id`
- `steps.<name>.record`
- `steps.<name>.records`
- `steps.<name>.map_by_<field>`

## 6.2 `request`

Standard HTTP:

```yaml
- request:
    name: fetch
    method: GET
    url: /path/{{args.id}}
    params:
      limit: "{{args.limit}}"
    headers: {}
    body:
      encoding: json      # json | form | text | bytes
      template:
        key: "{{args.value}}"
```

Provider request:

```yaml
- request:
    name: fetch
    provider: x_graphql
    operation: SearchTimeline
    variables:
      rawQuery: "{{args.query}}"
      count: "{{args.limit}}"
```

## 6.3 `fanout`

```yaml
- fanout:
    name: items
    items_from: "{{steps.ids.json}}"
    limit: "{{args.limit}}"
    request:
      method: GET
      url: /item/{{item}}.json
```

## 6.4 `parse`

```yaml
- parse:
    name: parsed
    from: fetch
    format: json          # json | json_list | html
    extract: "$.items[*]"
    item_ops:
      - flatten_tree:
          include_path: "$.kind"
          include_equals: t1
          children_path: "$.data.replies.data.children[*]"
          item_path: "$.data"
          depth_path: "$.depth"
          depth_field: "__depth"
          indent_field: "__indent"
    fields:
      - name: title
        from: "$.title"
      - name: user_name
        from: "$.user_id"
        ops:
          - map_lookup:
              from: "steps.users.map_by_id"
              default: unknown
    post_ops:
      - reverse
```

Optional custom parser escape hatch:

```yaml
- parse:
    name: parsed
    from: fetch
    parser: custom
    script: parsers/custom_parser.py
```

## 6.5 `transform`

```yaml
- transform:
    name: sorted
    from: parsed
    ops:
      - sort:
          by: score
          order: desc
      - limit: 20
```

---

## 7. Parse Field Sources and Ops

Field source:

- `from: "$.path"`
- `from: { coalesce: ["$.a", "$.b"] }`

Supported field ops:

- `map_lookup`
- `regex_replace`
- `append_urls`
- `join`
- `add`
- `template`
- all built-in transforms (`int`, `round`, `lowercase`, `uppercase`, `strip_html`, `timestamp`, `x_datetime`, `x_date`, `truncate:N`)

Item ops:

- `flatten_tree`

Record post ops:

- `reverse`
- `sort`
- `limit`
- `filter_not_empty`
- `concat`

---

## 8. Context and Templates

Templates use `{{ ... }}` and can reference runtime context:

- `{{args.query}}`
- `{{steps.channel.id}}`
- `{{item}}` (inside fanout)
- `{{index}}` (inside fanout)

---

## 9. Output

```yaml
output:
  from_step: parsed
  default_fields: [title, score, url]
  default_format: table   # table | json | csv | plain | md
```

Global CLI flags still apply:

- `--format`
- `--fields`
- `--no-truncate` (disable parser-level truncation rules like `truncate` / `truncate:N`)
- `--sort` / `--sort-by`
- `--limit`
- `--raw`
- `--trace`
- `--verbose`

---

## 10. Validate vs Lint

Adapter quality checks are split into two commands:

| Command | Scope | Fails on |
|---|---|---|
| `web2cli adapters validate` | Structural checks | invalid schema shape, unsupported arg types, missing pipeline, missing scripts for custom parser |
| `web2cli adapters lint` | Semantic checks | unknown step refs, unknown provider, invalid ops/transforms, bad template references, invalid auth inject/capture config |

Use both in CI:

1. `validate` first (hard schema gate)
2. `lint` second (semantic correctness gate)

---

## 11. Runtime Error Semantics

Execution rules:

- A step error (`request`, `resolve`, `parse`, `transform`, `fanout`) MUST fail the command with non-zero exit.
- Unresolved `resolve` input MUST fail with an explanatory error listing available candidates.
- `parse` producing an empty record list is not an error by itself; CLI prints `No results.` and exits `0`.
- `--raw` returns last response body (if any) and exits `0` unless execution failed earlier.
- HTTP/network failures are surfaced as command errors (exit `1`).

---

## 12. Trace (`--trace`)

`--trace` prints runtime diagnostics to stderr:

- step start/finish (`step[i] type:name`)
- request/response metadata (method, URL, status, payload size)
- resource cache events (hit/miss/write)
- final output summary (`records=N`)

Example:

```text
command=reddit.thread steps=4 args=['id', 'limit']
step[0] request:fetch start
step[0] request:fetch: request GET https://www.reddit.com/comments/....json
step[0] request:fetch: response status=200 body_bytes=12345 json=yes
step[1] parse:post done output=list[1]
result records=21 output_from=parsed last_response_body_bytes=12345
```

Use `--trace` when:

- authoring a new adapter
- debugging empty outputs
- diagnosing unexpected step dependencies

---

## 13. Provider Plugins

Provider plugins SHOULD live with the adapter that uses them:

```text
adapters/<domain>/providers/<provider_name>.py
```

Runtime loads provider modules dynamically:

- first from the current adapter directory (`adapter_dir/providers`)
- then from known adapter roots (`adapters/`, `~/.web2cli/adapters/`)

Provider handles protocol-specific behavior (query-id refresh, transaction headers, etc), while adapter YAML stays declarative.

---

## 14. Compatibility Policy

web2cli runtime is v0.2-only.

- v0.1 adapters are not supported.
- Commands must define `pipeline`.
- Optional `parse: { parser: custom, script: ... }` remains available as an escape hatch.

---

## 15. Spec Versioning Policy

Versioning rules:

- `0.2.x` MAY add backward-compatible fields, ops, or provider capabilities.
- `0.2.x` MUST NOT silently change existing semantics.
- Breaking schema/runtime changes MUST use a new minor spec line (for example `0.3`).
- Adapters SHOULD pin `meta.spec_version` explicitly.
