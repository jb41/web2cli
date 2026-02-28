# LLM Adapter Playbook

Practical workflow for generating high-quality web2cli adapters with an LLM.

## Goal

Produce a declarative adapter (`web2cli.yaml`) that:

1. matches the v0.2 spec,
2. passes `validate` and `lint`,
3. works on real requests.

## Inputs You Need

Before generation, provide the LLM:

1. target domain and base URL,
2. desired commands and CLI args,
3. sample responses (JSON/HTML) for each command,
4. auth method (cookies/token/injection target),
5. browser-capture rules for tokens if `login --browser` should auto-capture them (`auth.methods[].capture`),
6. expected output fields per command.

Missing samples are the most common cause of weak adapters.

## Recommended Workflow

1. Start from minimal adapter template in `docs/adapter-spec.md`.
2. Implement one command end-to-end first.
3. Add `resources` only after first command works.
4. Reuse parse/transform patterns across commands.
5. Run checks:
   - `web2cli adapters validate`
   - `web2cli adapters lint`
   - `web2cli <domain> <command> ... --trace`
6. Iterate until shape and output are stable, then add remaining commands.

## Definition of Done

Adapter is done when all are true:

1. `validate` passes.
2. `lint` passes with no errors.
3. Trace shows expected step flow (no missing `from`, no empty unexpected parse output).
4. Outputs contain expected fields in expected format.
5. No custom parser script is used unless justified.

## Prompt Template

Use this as a base prompt for an LLM:

```text
Create or update a web2cli adapter for <domain>.

Constraints:
- Follow docs/adapter-spec.md (spec version 0.2).
- Use declarative pipeline steps only unless strictly necessary.
- Prefer resources for reusable lookups.
- Do not introduce custom parser scripts unless declarative parse is insufficient.
- Keep field names stable and user-facing.

Commands to implement:
<list commands + args + expected fields>

Auth:
<cookies/token/inject target details + optional token capture rule>

Samples:
<request/response snippets for each command>

After generating YAML, run and fix until:
1) web2cli adapters validate passes
2) web2cli adapters lint passes
3) at least one --trace run looks correct
```

## Common Patterns

### REST list endpoint

Use:

1. `request` with params/body template,
2. `parse format: json`,
3. `extract` + field mappings,
4. optional `post_ops` (`sort`, `limit`, `reverse`).

### Name -> ID resolution

Use:

1. reusable `resources.<name>`,
2. `resolve` step with `input`, `by`, `value`,
3. downstream request references `{{steps.<resolve_name>.id}}`.

### HTML pages

Use:

1. `parse format: html`,
2. CSS selectors with `extract` and per-field `path`,
3. transforms (`int`, `strip_html`, `truncate:N`) for normalization.

### Fan-out (IDs -> details)

Use:

1. first `request` to get IDs,
2. `fanout` over items,
3. `parse format: json_list`.

## Escalation Rules

Only use custom parser scripts if:

1. recursive structure cannot be represented with `item_ops.flatten_tree`,
2. output requires multi-source merge not expressible by current parse + transform ops,
3. upstream response is highly irregular and cannot be mapped reliably.

If a custom script is used, include a short justification in PR notes.
