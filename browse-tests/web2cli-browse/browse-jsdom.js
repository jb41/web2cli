#!/usr/bin/env node

/**
 * web2cli browse --snapshot (jsdom variant)
 *
 * Usage:
 *   node browse-jsdom.js <url>                    # snapshot a11y tree
 *   node browse-jsdom.js <url> --html             # dump raw HTML
 *   node browse-jsdom.js <url> --json             # output JSON for LLM processing
 *   node browse-jsdom.js <url> --verbose          # show timing and memory
 *   node browse-jsdom.js <url> --timeout=ms       # set custom timeout (default 10000ms)
 *   node browse-jsdom.js <url> --no-js            # skip JS execution (fast, SSR-only)
 */

import pkg from "jsdom";
const { JSDOM, ResourceLoader, VirtualConsole } = pkg;

// ============================================================
// CONFIG
// ============================================================

const url = process.argv[2];
const flagHtml = process.argv.includes("--html");
const flagVerbose = process.argv.includes("--verbose");
const flagJson = process.argv.includes("--json");
const flagNoJs = process.argv.includes("--no-js");
const timeout = parseInt(
  process.argv.find((a) => a.startsWith("--timeout="))?.split("=")[1] || "10000"
);

if (!url) {
  console.error(
    "Usage: node browse-jsdom.js <url> [--html] [--json] [--verbose] [--no-js] [--timeout=ms]"
  );
  process.exit(1);
}

// ============================================================
// LOAD PAGE
// ============================================================

const t0 = Date.now();
if (flagVerbose) console.error(`[browse] Loading ${url} ...`);

const virtualConsole = new VirtualConsole();
virtualConsole.on("error", (...args) => {
  if (flagVerbose) console.error("[PAGE ERROR]", ...args);
});
virtualConsole.on("warn", () => {});
virtualConsole.on("info", () => {});
virtualConsole.on("dir", () => {});

const userAgent =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36";

const jsdomOptions = {
  referrer: url,
  userAgent,
  runScripts: flagNoJs ? undefined : "dangerously",
  resources: flagNoJs ? undefined : "usable",
  pretendToBeVisual: true,
  virtualConsole,
  beforeParse(window) {
    // Stub missing globals that crash page scripts
    const nullSink = new Proxy(function () {}, {
      get: (t, p) => {
        if (p === Symbol.toPrimitive) return () => "";
        if (p === Symbol.iterator) return undefined;
        if (p === "then") return undefined;
        return nullSink;
      },
      apply: () => nullSink,
      construct: () => nullSink,
      set: () => true,
    });

    const STUB_GLOBALS = ["InstantClick", "I18n", "isTouchDevice"];
    for (const name of STUB_GLOBALS) {
      if (!(name in window)) {
        window[name] = nullSink;
      }
    }

    // Fix navigator.platform
    try {
      Object.defineProperty(window.navigator, "platform", {
        value: "MacIntel",
        configurable: true,
      });
    } catch {}
  },
};

// Prevent uncaught script errors from killing the process
process.on("uncaughtException", (err) => {
  if (flagVerbose) console.error("[PAGE ERROR]", err.message);
});

// Fetch HTML — try system curl first (macOS BoringSSL passes more anti-bot checks),
// fall back to Node fetch if curl is unavailable.
async function fetchHTML(targetUrl) {
  const { execFileSync } = await import("child_process");
  try {
    const html = execFileSync("curl", [
      "-sL", "--max-time", "15",
      "-H", `User-Agent: ${userAgent}`,
      "-H", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
      "-H", "Accept-Language: en-US,en;q=0.9",
      "-H", "Accept-Encoding: identity",
      targetUrl,
    ], { maxBuffer: 20 * 1024 * 1024 }).toString();
    if (flagVerbose) console.error(`[browse] Fetched via system curl (${html.length} bytes)`);
    return html;
  } catch {
    if (flagVerbose) console.error("[browse] curl failed, falling back to Node fetch");
    const res = await fetch(targetUrl, {
      headers: { "User-Agent": userAgent, "Accept": "text/html" },
      redirect: "follow",
    });
    if (!res.ok) console.error(`[browse] HTTP ${res.status} ${res.statusText}`);
    return res.text();
  }
}

let dom;
try {
  const html = await fetchHTML(url);
  dom = new JSDOM(html, { ...jsdomOptions, url });
} catch (err) {
  console.error(`[browse] Navigation error: ${err.message}`);
  process.exit(1);
}

// Activate deferred content: some sites (Reddit) put SSR content inside <template>
// elements, activated by JS at runtime. Inline them into the live DOM so the a11y
// tree can see them.
{
  const doc_ = dom.window.document;

  // Strategy 1: <suspense-replace target="#id" template="selector"> pattern (Reddit)
  for (const replacer of doc_.querySelectorAll("suspense-replace")) {
    const tmplSelector = replacer.getAttribute("template");
    const targetSelector = replacer.getAttribute("target");
    if (!tmplSelector || !targetSelector) continue;
    const tmpl = doc_.querySelector(tmplSelector);
    const target = doc_.querySelector(targetSelector);
    if (tmpl?.innerHTML && target) {
      const container = doc_.createElement("div");
      container.innerHTML = tmpl.innerHTML;
      target.replaceWith(container);
      if (flagVerbose) console.error(`[browse] Activated suspense content -> ${targetSelector} (${container.querySelectorAll("*").length} elements)`);
    }
  }

  // Strategy 2: any remaining large <template> in body (>1KB) — likely deferred SSR
  for (const tmpl of doc_.querySelectorAll("body > template")) {
    if (tmpl.innerHTML.length < 1024) continue;
    const container = doc_.createElement("div");
    container.innerHTML = tmpl.innerHTML;
    tmpl.replaceWith(container);
    if (flagVerbose) console.error(`[browse] Inlined body template (${container.querySelectorAll("*").length} elements)`);
  }
}

const doc = dom.window.document;

// Wait for DOM to stabilize (scripts may still be fetching/rendering)
if (!flagNoJs) {
  const settleMs = 500;
  let lastCount = doc.querySelectorAll("*").length;
  let stableAt = Date.now();

  await new Promise((resolve) => {
    const hardTimer = setTimeout(() => {
      clearInterval(pollTimer);
      if (flagVerbose)
        console.error(`[browse] Timeout after ${timeout}ms — using partial DOM`);
      resolve();
    }, timeout);

    const pollTimer = setInterval(() => {
      const count = doc.querySelectorAll("*").length;
      if (count !== lastCount) {
        lastCount = count;
        stableAt = Date.now();
      } else if (Date.now() - stableAt >= settleMs) {
        clearInterval(pollTimer);
        clearTimeout(hardTimer);
        if (flagVerbose)
          console.error(
            `[browse] DOM stabilized (${count} elements, settled for ${settleMs}ms)`
          );
        resolve();
      }
    }, 100);
  });
}

const loadTime = Date.now() - t0;

if (flagVerbose) {
  console.error(`[browse] Loaded in ${loadTime}ms`);
  console.error(`[browse] Title: "${doc.title}"`);
  console.error(
    `[browse] DOM elements: ${doc.querySelectorAll("*").length}`
  );
  console.error(
    `[browse] HTML size: ${doc.documentElement?.outerHTML?.length || 0} chars`
  );
}

// ============================================================
// MODE: --html
// ============================================================

if (flagHtml) {
  console.log(doc.documentElement?.outerHTML || "");
  dom.window.close();
  process.exit(0);
}

// ============================================================
// A11Y TREE EXTRACTION
// ============================================================

function extractA11yTree(root) {
  const nodes = [];
  let idCounter = 0;

  const SKIP_TAGS = new Set([
    "script", "style", "svg", "path", "circle", "rect", "line", "polygon",
    "polyline", "ellipse", "g", "defs", "clippath", "mask", "use",
    "noscript", "link", "meta", "head", "html", "br", "hr", "wbr",
    "template", "slot", "source", "track",
  ]);

  const ROLE_MAP = {
    a: "link", button: "button", input: "textbox", select: "combobox",
    textarea: "textbox", img: "image", video: "video", audio: "audio",
    h1: "heading", h2: "heading", h3: "heading",
    h4: "heading", h5: "heading", h6: "heading",
    nav: "navigation", main: "main", form: "form",
    table: "table", thead: "rowgroup", tbody: "rowgroup",
    tr: "row", th: "columnheader", td: "cell",
    ul: "list", ol: "list", li: "listitem",
    section: "region", article: "article", aside: "complementary",
    header: "banner", footer: "contentinfo", dialog: "dialog",
    details: "group", summary: "button", label: "label",
    fieldset: "group", legend: "legend", p: "paragraph",
    figure: "figure", figcaption: "caption",
    time: "time", mark: "mark", code: "code", pre: "code",
    blockquote: "blockquote", strong: "strong", em: "emphasis",
  };

  const INTERACTIVE_TAGS = new Set([
    "a", "button", "input", "select", "textarea", "details", "summary",
  ]);

  function isHidden(node) {
    if (node.getAttribute("aria-hidden") === "true") return true;
    if (node.getAttribute("hidden") !== null) return true;
    const style = node.getAttribute("style") || "";
    if (style.includes("display:none") || style.includes("display: none"))
      return true;
    if (
      style.includes("visibility:hidden") ||
      style.includes("visibility: hidden")
    )
      return true;
    return false;
  }

  function getAccessibleName(node, tag) {
    let name =
      node.getAttribute("aria-label") ||
      node.getAttribute("alt") ||
      node.getAttribute("title") ||
      node.getAttribute("placeholder") ||
      "";

    if (!name) {
      name = Array.from(node.childNodes)
        .filter((n) => n.nodeType === 3)
        .map((n) => n.textContent.trim())
        .filter(Boolean)
        .join(" ")
        .substring(0, 100);
    }

    return name.replace(/\s+/g, " ").trim();
  }

  function walk(node, depth) {
    if (!node || !node.tagName) return;

    const tag = node.tagName.toLowerCase();
    if (SKIP_TAGS.has(tag)) return;
    if (isHidden(node)) return;

    const role = node.getAttribute("role") || ROLE_MAP[tag] || "";
    const isInteractive = INTERACTIVE_TAGS.has(tag);
    const name = getAccessibleName(node, tag);

    const shouldShow = isInteractive || !!role || name.length > 0;

    if (shouldShow) {
      const nodeId = isInteractive ? idCounter++ : null;
      const indent = "  ".repeat(depth);
      const idStr = nodeId !== null ? `[${nodeId}]` : "";

      let line = `${indent}${idStr ? idStr + " " : ""}${role || tag}`;

      if (tag === "a") {
        if (name) line += ` "${name}"`;
        const href = node.getAttribute("href") || "";
        if (href && href.length < 80) line += ` -> ${href}`;
      } else if (tag === "input") {
        const type = node.getAttribute("type") || "text";
        line += `[${type}]`;
        if (name) line += ` "${name}"`;
        if (node.value) line += ` val="${node.value}"`;
      } else if (tag === "select") {
        if (name) line += ` "${name}"`;
        const selected = node.querySelector("option[selected]");
        if (selected) line += ` selected="${selected.textContent?.trim()}"`;
      } else if (tag === "button") {
        if (name) line += ` "${name}"`;
        if (node.disabled) line += " (disabled)";
      } else if (tag.match(/^h[1-6]$/)) {
        const fullText = (node.textContent || "").trim().substring(0, 80);
        line += `(${tag}) "${fullText}"`;
      } else if (tag === "img") {
        if (name) line += ` "${name}"`;
        const src = node.getAttribute("src") || "";
        if (src && src.length < 60) line += ` src=${src}`;
      } else if (name) {
        line += ` "${name}"`;
      }

      nodes.push({
        line,
        id: nodeId,
        tag,
        role: role || tag,
        name,
        depth,
        element: node,
      });
    }

    const nextDepth = depth + (shouldShow && (isInteractive || !!role) ? 1 : 0);
    if (node.children) {
      for (const child of node.children) {
        walk(child, nextDepth);
      }
    }
  }

  if (root) walk(root, 0);

  return {
    lines: nodes.map((n) => n.line),
    nodes,
    interactiveCount: idCounter,
  };
}

// ============================================================
// OUTPUT
// ============================================================

const tree = extractA11yTree(doc.body);

if (flagJson) {
  const output = {
    url,
    title: doc.title,
    loadTime,
    elements: doc.querySelectorAll("*").length,
    tree: tree.nodes.map((n) => ({
      id: n.id,
      role: n.role,
      name: n.name,
      tag: n.tag,
      depth: n.depth,
    })),
    interactiveCount: tree.interactiveCount,
    memory: Math.round(process.memoryUsage().heapUsed / 1024 / 1024),
  };
  console.log(JSON.stringify(output, null, 2));
} else {
  console.log(`Page: ${doc.title || url}`);
  console.log(
    `Loaded: ${loadTime}ms | DOM: ${doc.querySelectorAll("*").length} elements | Interactive: ${tree.interactiveCount}`
  );
  console.log();

  for (const line of tree.lines) {
    console.log(line);
  }

  console.log();
  console.log(
    `(${tree.lines.length} nodes, ${tree.interactiveCount} interactive)`
  );

  const mem = process.memoryUsage();
  if (flagVerbose) {
    console.error(
      `\n[browse] RSS: ${Math.round(mem.rss / 1024 / 1024)}MB | Heap: ${Math.round(mem.heapUsed / 1024 / 1024)}MB`
    );
  }
}

dom.window.close();
