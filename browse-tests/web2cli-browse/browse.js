#!/usr/bin/env node

/**
 * web2cli browse --snapshot MVP
 *
 * Usage:
 *   node browse.js <url>                    # snapshot a11y tree
 *   node browse.js <url> --html             # dump raw HTML
 *   node browse.js <url> --interactive      # snapshot + interactive REPL
 *   node browse.js <url> --json             # output JSON for LLM processing
 *   node browse.js <url> --cookies=path     # load cookies from JSON file
 *   node browse.js <url> --timeout=ms       # set custom timeout (default 15000ms)
 *
 * Examples:
 *   node browse.js https://github.com/jb41/web2cli
 *   node browse.js https://amazon.com
 *   node browse.js https://news.ycombinator.com
 */

import { Browser, BrowserErrorCaptureEnum } from "happy-dom";

// ============================================================
// CONFIG
// ============================================================

const url = process.argv[2];
const flagHtml = process.argv.includes("--html");
const flagInteractive = process.argv.includes("--interactive");
const flagVerbose = process.argv.includes("--verbose");
const flagJson = process.argv.includes("--json");
const flagCookies = process.argv.find(a => a.startsWith('--cookies='))?.split('=')[1];
const timeout = parseInt(process.argv.find(a => a.startsWith('--timeout='))?.split('=')[1] || '15000');


if (!url) {
  console.error("Usage: node browse.js <url> [--html] [--json] [--interactive] [--verbose] [--cookies=path] [--timeout=ms]");
  console.error("\nExamples:");
  console.error("  node browse.js https://github.com/jb41/web2cli");
  console.error("  node browse.js https://amazon.com --verbose");
  console.error("  node browse.js https://news.ycombinator.com --json");
  console.error("  node browse.js https://example.com --cookies=cookies.json");
  console.error("  node browse.js https://example.com --timeout=20000");
  process.exit(1);
}

// ============================================================
// LOAD PAGE
// ============================================================

const t0 = Date.now();

const browser = new Browser({
  settings: {
    errorCapture: BrowserErrorCaptureEnum.processLevel,
    enableJavaScriptEvaluation: true,
    suppressInsecureJavaScriptEnvironmentWarning: true,
    disableCSSFileLoading: true,
    navigator: {
      userAgent:
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    },
    fetch: {
      disableSameOriginPolicy: true,
    },
  },
});

const page = browser.newPage();

if (flagVerbose) console.error(`[browse] Loading ${url} ...`);

if (flagCookies) {
  const fs = await import('fs');
  const cookieData = JSON.parse(fs.readFileSync(flagCookies, 'utf-8'));
  // web2cli format: array of {name, value, domain, path, ...}
  const cookieContainer = page.mainFrame.window.document.defaultView?.document?.cookie;
  // Or use the CookieContainer API:
  for (const cookie of cookieData) {
    page.context.cookieContainer.addCookies([{
      name: cookie.name,
      value: cookie.value,
      domain: cookie.domain || new URL(url).hostname,
      path: cookie.path || '/',
      secure: cookie.secure || false,
      httpOnly: cookie.httpOnly || false,
    }]);
  }
  if (flagVerbose) console.error(`[browse] Loaded ${cookieData.length} cookies`);
}

const virtualConsole = page.mainFrame.window.console;
const origError = virtualConsole.error;
virtualConsole.error = (...args) => {
  console.error('[PAGE ERROR]', ...args);
  origError?.apply(virtualConsole, args);
};

try {
  await page.goto(url);
  
  // Race between waitUntilComplete and timeout
  await Promise.race([
    page.waitUntilComplete(),
    new Promise((_, reject) => 
      setTimeout(() => reject(new Error('Timeout')), timeout)
    ),
  ]).catch(err => {
    if (flagVerbose) console.error(`[browse] ${err.message} after ${timeout}ms — using partial DOM`);
    // Abort remaining operations
    page.abort();
  });
} catch (err) {
  console.error(`[browse] Navigation error: ${err.message}`);
}

const doc = page.mainFrame.document;
const loadTime = Date.now() - t0;

if (flagVerbose) {
  console.error(`[browse] Loaded in ${loadTime}ms`);
  console.error(`[browse] Title: "${doc.title}"`);
  console.error(`[browse] DOM elements: ${doc.querySelectorAll("*").length}`);
  console.error(`[browse] HTML size: ${(doc.documentElement?.outerHTML?.length || 0)} chars`);
}

// ============================================================
// MODE: --html (dump raw HTML)
// ============================================================

if (flagHtml) {
  console.log(doc.documentElement?.outerHTML || "");
  await browser.close();
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
    if (style.includes("display:none") || style.includes("display: none")) return true;
    if (style.includes("visibility:hidden") || style.includes("visibility: hidden")) return true;
    return false;
  }

  function getAccessibleName(node, tag) {
    // Priority: aria-label > aria-labelledby (skip for now) > alt > title > placeholder > direct text
    let name =
      node.getAttribute("aria-label") ||
      node.getAttribute("alt") ||
      node.getAttribute("title") ||
      node.getAttribute("placeholder") ||
      "";

    if (!name) {
      // Get direct text children only (not deep text)
      name = Array.from(node.childNodes)
        .filter((n) => n.nodeType === 3) // TEXT_NODE
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

    const shouldShow = isInteractive || !!role || (name.length > 0);

    if (shouldShow) {
      const nodeId = isInteractive ? idCounter++ : null;
      const indent = "  ".repeat(depth);
      const idStr = nodeId !== null ? `[${nodeId}]` : "";

      let line = `${indent}${idStr ? idStr + " " : ""}${role || tag}`;

      // Add details based on element type
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
        // Show selected option
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

    // Walk children
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
  // JSON output for piping to LLM
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
  // Human-readable output
  console.log(`Page: ${doc.title || url}`);
  console.log(`Loaded: ${loadTime}ms | DOM: ${doc.querySelectorAll("*").length} elements | Interactive: ${tree.interactiveCount}`);
  console.log();

  for (const line of tree.lines) {
    console.log(line);
  }

  console.log();
  console.log(`(${tree.lines.length} nodes, ${tree.interactiveCount} interactive)`);

  // Memory stats
  const mem = process.memoryUsage();
  if (flagVerbose) {
    console.error(`\n[browse] RSS: ${Math.round(mem.rss / 1024 / 1024)}MB | Heap: ${Math.round(mem.heapUsed / 1024 / 1024)}MB`);
  }
}

// ============================================================
// INTERACTIVE MODE
// ============================================================

if (flagInteractive) {
  const readline = await import("readline");
  const rl = readline.createInterface({ input: process.stdin, output: process.stderr });

  console.error("\n--- Interactive Mode ---");
  console.error("Commands: click <id>, type <id> <text>, submit <id>, snapshot, tree, quit");

  const prompt = () => {
    rl.question("\n> ", async (cmd) => {
      const parts = cmd.trim().split(/\s+/);
      const action = parts[0];

      try {
        if (action === "quit" || action === "q" || action === "exit") {
          rl.close();
          await browser.close();
          process.exit(0);
        }

        if (action === "click") {
          const targetId = parseInt(parts[1]);
          const node = tree.nodes.find((n) => n.id === targetId);
          if (!node) {
            console.error(`  Element [${targetId}] not found`);
          } else {
            node.element.click();
            await page.waitUntilComplete();
            console.error(`  Clicked [${targetId}] ${node.role} "${node.name}"`);
          }
        }

        if (action === "type") {
          const targetId = parseInt(parts[1]);
          const text = parts.slice(2).join(" ");
          const node = tree.nodes.find((n) => n.id === targetId);
          if (!node) {
            console.error(`  Element [${targetId}] not found`);
          } else {
            node.element.value = text;
            node.element.dispatchEvent(
              new page.mainFrame.window.Event("input", { bubbles: true })
            );
            console.error(`  Typed "${text}" into [${targetId}]`);
          }
        }

        if (action === "submit") {
          const targetId = parseInt(parts[1]);
          const node = tree.nodes.find((n) => n.id === targetId);
          if (!node) {
            console.error(`  Element [${targetId}] not found`);
          } else {
            // Find parent form or submit the element
            const form = node.element.closest("form") || node.element;
            form.dispatchEvent(
              new page.mainFrame.window.Event("submit", {
                bubbles: true,
                cancelable: true,
              })
            );
            await page.waitUntilComplete();
            console.error(`  Submitted form for [${targetId}]`);
          }
        }

        if (action === "snapshot" || action === "tree") {
          // Re-extract tree after interactions
          const newTree = extractA11yTree(doc.body);
          // Update tree reference
          tree.nodes.length = 0;
          tree.lines.length = 0;
          newTree.nodes.forEach((n) => tree.nodes.push(n));
          newTree.lines.forEach((l) => tree.lines.push(l));
          tree.interactiveCount = newTree.interactiveCount;

          console.log();
          for (const line of tree.lines) {
            console.log(line);
          }
          console.log(`\n(${tree.lines.length} nodes, ${tree.interactiveCount} interactive)`);
        }

        if (action === "html") {
          console.log(doc.body?.innerHTML?.substring(0, 5000));
        }
      } catch (err) {
        console.error(`  Error: ${err.message}`);
      }

      prompt();
    });
  };
  prompt();
} else {
  await browser.close();
}
