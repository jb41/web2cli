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
