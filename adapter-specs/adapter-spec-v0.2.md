# web2cli Adapter Specification v0.2

> Every website is a command.

---

## Philosophy

v0.2 moves behavior from adapter-local Python scripts into declarative YAML.

Main principles:

1. Pipeline-based command execution (`resolve -> request -> fanout -> parse -> transform`)
2. Reusable named resources (with cache + optional pagination)
3. Explicit body encodings (`json`, `form`, `text`, `bytes`)
4. Auth injection policy in adapter spec
5. Provider plugins for protocol-heavy sites (e.g. `x_graphql`)

Custom Python is still an escape hatch, not the default.

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
```

Notes:

- Multiple methods can be combined (e.g. cookies + token from env vars).
- `inject` controls where auth value is written into the request.
- If no `inject` is given for token auth, runtime defaults to `Authorization` header.

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
- `--sort` / `--sort-by`
- `--limit`
- `--raw`
- `--trace`
- `--verbose`

---

## 10. Provider Plugins

Provider plugins live in core runtime (not adapter-local scripts).

Current built-in provider:

- `x_graphql`

Provider handles protocol-specific behavior (query-id refresh, transaction headers, etc), while adapter YAML stays declarative.

---

## 11. Compatibility Policy

web2cli runtime is v0.2-only.

- v0.1 adapters are not supported.
- Commands must define `pipeline`.
- Optional `parse: { parser: custom, script: ... }` remains available as an escape hatch.
