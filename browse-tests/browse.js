#!/usr/bin/env node

/**
 * web2cli browse (jsdom variant)
 *
 * Usage:
 *   node browse-jsdom.js <url>                    # snapshot a11y tree
 *   node browse-jsdom.js <url> --html             # dump raw HTML
 *   node browse-jsdom.js <url> --json             # output JSON for LLM processing
 *   node browse-jsdom.js <url> --verbose          # show timing and memory
 *   node browse-jsdom.js <url> --timeout=ms       # set custom timeout (default 10000ms)
 *   node browse-jsdom.js <url> --interactive      # REPL mode: type commands to interact
 */

import pkg from "jsdom";
const { JSDOM, VirtualConsole } = pkg;
import { createInterface } from "readline";
import TurndownService from "turndown";
import { readFileSync } from "fs";

// Load .env
try {
  const envContent = readFileSync(new URL(".env", import.meta.url), "utf8");
  for (const line of envContent.split("\n")) {
    const [k, ...v] = line.split("=");
    if (k && v.length) process.env[k.trim()] = v.join("=").trim();
  }
} catch {}

// ============================================================
// CONFIG
// ============================================================

const url = process.argv[2];
const flagHtml = process.argv.includes("--html");
const flagVerbose = process.argv.includes("--verbose");
const flagJson = process.argv.includes("--json");
const flagInteractive = process.argv.includes("--interactive");
const flagTask = process.argv.find((a) => a.startsWith("--task="))?.split("=").slice(1).join("=")
  || (process.argv.includes("--task") ? process.argv[process.argv.indexOf("--task") + 1] : null);
const timeout = parseInt(
  process.argv.find((a) => a.startsWith("--timeout="))?.split("=")[1] || "10000"
);

if (!url) {
  console.error(
    "Usage: node browse-jsdom.js <url> [--html] [--json] [--verbose] [--interactive] [--timeout=ms]"
  );
  process.exit(1);
}

// ============================================================
// SHARED STATE
// ============================================================

let dom;
let doc;
let currentUrl = url;
let lastTree = null; // keeps id→element mapping

const userAgent =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36";

// ============================================================
// JSDOM SETUP
// ============================================================

const virtualConsole = new VirtualConsole();
virtualConsole.on("error", (...args) => {
  if (flagVerbose) console.error("[PAGE ERROR]", ...args);
});
virtualConsole.on("warn", () => {});
virtualConsole.on("info", () => {});
virtualConsole.on("dir", () => {});

function makeJsdomOptions(pageUrl) {
  return {
    url: pageUrl,
    referrer: pageUrl,
    userAgent,
    runScripts: "dangerously",
    resources: "usable",
    pretendToBeVisual: true,
    virtualConsole,
    beforeParse(window) {
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

      try {
        Object.defineProperty(window.navigator, "platform", {
          value: "MacIntel",
          configurable: true,
        });
      } catch {}
    },
  };
}

// Prevent uncaught script errors from killing the process
process.on("uncaughtException", (err) => {
  if (flagVerbose) console.error("[PAGE ERROR]", err.message);
});

// ============================================================
// FETCH HTML
// ============================================================

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

// ============================================================
// LOAD / NAVIGATE
// ============================================================

async function loadPage(targetUrl) {
  const t0 = Date.now();
  if (flagVerbose) console.error(`[browse] Loading ${targetUrl} ...`);

  if (dom) {
    try { dom.window.close(); } catch {}
  }

  const html = await fetchHTML(targetUrl);
  dom = new JSDOM(html, makeJsdomOptions(targetUrl));
  doc = dom.window.document;
  currentUrl = targetUrl;

  // Activate deferred content (Reddit suspense pattern)
  activateTemplates(doc);

  // Wait for DOM to stabilize
  await waitForStable(doc);

  const loadTime = Date.now() - t0;
  if (flagVerbose) {
    console.error(`[browse] Loaded in ${loadTime}ms`);
    console.error(`[browse] Title: "${doc.title}"`);
    console.error(`[browse] DOM elements: ${doc.querySelectorAll("*").length}`);
  }

  return loadTime;
}

function activateTemplates(document) {
  for (const replacer of document.querySelectorAll("suspense-replace")) {
    const tmplSelector = replacer.getAttribute("template");
    const targetSelector = replacer.getAttribute("target");
    if (!tmplSelector || !targetSelector) continue;
    const tmpl = document.querySelector(tmplSelector);
    const target = document.querySelector(targetSelector);
    if (tmpl?.innerHTML && target) {
      const container = document.createElement("div");
      container.innerHTML = tmpl.innerHTML;
      target.replaceWith(container);
      if (flagVerbose) console.error(`[browse] Activated suspense -> ${targetSelector}`);
    }
  }

  for (const tmpl of document.querySelectorAll("body > template")) {
    if (tmpl.innerHTML.length < 1024) continue;
    const container = document.createElement("div");
    container.innerHTML = tmpl.innerHTML;
    tmpl.replaceWith(container);
    if (flagVerbose) console.error(`[browse] Inlined body template`);
  }
}

async function waitForStable(document, timeoutMs) {
  const settleMs = 500;
  const maxWait = timeoutMs || timeout;
  let lastCount = document.querySelectorAll("*").length;
  let stableAt = Date.now();

  await new Promise((resolve) => {
    const hardTimer = setTimeout(() => {
      clearInterval(pollTimer);
      if (flagVerbose) console.error(`[browse] Timeout after ${maxWait}ms — using partial DOM`);
      resolve();
    }, maxWait);

    const pollTimer = setInterval(() => {
      const count = document.querySelectorAll("*").length;
      if (count !== lastCount) {
        lastCount = count;
        stableAt = Date.now();
      } else if (Date.now() - stableAt >= settleMs) {
        clearInterval(pollTimer);
        clearTimeout(hardTimer);
        if (flagVerbose) console.error(`[browse] DOM stabilized (${count} elements)`);
        resolve();
      }
    }, 100);
  });
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
// SNAPSHOT — prints a11y tree + returns it
// ============================================================

function refreshTree() {
  lastTree = extractA11yTree(doc.body);
  return lastTree;
}

function printStatus() {
  const elCount = doc.querySelectorAll("*").length;
  const interactive = lastTree ? lastTree.interactiveCount : "?";
  console.log(`  Page: ${doc.title || "(no title)"}`);
  console.log(`  URL:  ${currentUrl}`);
  console.log(`  DOM:  ${elCount} elements | Interactive: ${interactive}`);
}

function snapshot() {
  const tree = refreshTree();

  console.log(`\nPage: ${doc.title || currentUrl}`);
  console.log(`URL: ${currentUrl}`);
  console.log(
    `DOM: ${doc.querySelectorAll("*").length} elements | Interactive: ${tree.interactiveCount}`
  );
  console.log();

  for (const line of tree.lines) {
    console.log(line);
  }

  console.log();
  console.log(`(${tree.lines.length} nodes, ${tree.interactiveCount} interactive)`);

  return tree;
}

// ============================================================
// ACTIONS
// ============================================================

function findNode(id) {
  if (!lastTree) return null;
  const numId = Number(id);
  return lastTree.nodes.find((n) => n.id === numId) || null;
}

function resolveUrl(href) {
  try {
    return new URL(href, currentUrl).href;
  } catch {
    return href;
  }
}

async function execClick(id) {
  const node = findNode(id);
  if (!node) {
    throw new Error(`No interactive element with id [${id}]`);
  }

  const el = node.element;
  const tag = node.tag;
  console.log(`  Clicked [${id}] ${node.role} "${node.name}"`);

  // If it's a link, check if there's a JS handler or if we need to navigate
  if (tag === "a") {
    const href = el.getAttribute("href") || "";
    const hasJsHandler = el.onclick || el.getAttribute("onclick");

    // Fire the click event — JS handlers will run
    el.click();

    // Short wait to let SPA routers do their thing
    await waitForStable(doc, 2000);

    // Check if location changed (SPA navigation)
    const newUrl = dom.window.location.href;
    if (newUrl !== currentUrl && newUrl !== "about:blank") {
      currentUrl = newUrl;
    } else if (!hasJsHandler && href && !href.startsWith("#") && !href.startsWith("javascript:")) {
      // No SPA handler caught it — do a full navigation
      const fullUrl = resolveUrl(href);
      await loadPage(fullUrl);
    }
  } else if (tag === "button" && el.closest("form") &&
    (el.getAttribute("type") || "submit") === "submit") {
    // Submit button inside a form — delegate to submit
    return execSubmit(id);
  } else {
    // Button, summary, etc. — just click it
    el.click();
    await waitForStable(doc, 2000);

    // Check if click triggered navigation
    const newUrl = dom.window.location.href;
    if (newUrl !== currentUrl && newUrl !== "about:blank") {
      currentUrl = newUrl;
    }
  }

  refreshTree();
  printStatus();
}

async function execType(id, text) {
  const node = findNode(id);
  if (!node) {
    throw new Error(`No interactive element with id [${id}]`);
  }

  const el = node.element;
  el.focus();

  // Set the value
  el.value = text;

  // Dispatch events that frameworks listen for
  el.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
  el.dispatchEvent(new dom.window.Event("change", { bubbles: true }));

  console.log(`  Typed "${text}" into [${id}] ${node.role} "${node.name}"`);
  await waitForStable(doc, 2000);
  refreshTree();
}

async function execSubmit(id) {
  const node = findNode(id);
  if (!node) {
    throw new Error(`No interactive element with id [${id}]`);
  }

  const el = node.element;

  // Find the form — either the element itself or the closest ancestor form
  const form = el.tagName.toLowerCase() === "form" ? el : el.closest("form");

  if (form) {
    // Try dispatching submit event first (frameworks often intercept this)
    const evt = new dom.window.Event("submit", { bubbles: true, cancelable: true });
    const cancelled = !form.dispatchEvent(evt);

    if (!cancelled) {
      // No JS handler caught it — extract form action and do a navigation
      const action = resolveUrl(form.getAttribute("action") || currentUrl);
      const method = (form.getAttribute("method") || "GET").toUpperCase();

      if (method === "GET") {
        const formData = new dom.window.FormData(form);
        const params = new URLSearchParams(formData);
        const navUrl = `${action}?${params.toString()}`;
        console.error(`[browse] Form GET -> ${navUrl}`);
        await loadPage(navUrl);
      } else {
        console.error(`[browse] Form POST -> ${action} (re-fetching as GET for now)`);
        await loadPage(action);
      }
    } else {
      // JS handler took over — wait and re-snapshot
      await waitForStable(doc, 2000);
    }
  } else {
    // No form — just click the element (like a submit button outside a form)
    el.click();
    await waitForStable(doc, 2000);
  }

  refreshTree();
  printStatus();
}

function getContentMarkdown() {
  const td = new TurndownService({
    headingStyle: "atx",
    codeBlockStyle: "fenced",
  });
  td.remove(["script", "style", "nav", "noscript", "svg"]);

  // Try to find main content area, skip nav/sidebar
  const contentRoot =
    doc.querySelector("article") ||
    doc.querySelector("main") ||
    doc.querySelector("[role='main']") ||
    doc.body;

  return td.turndown(contentRoot.innerHTML);
}

function execContent() {
  console.log(getContentMarkdown());
}

async function execGoto(targetUrl) {
  const fullUrl = resolveUrl(targetUrl);
  await loadPage(fullUrl);
  refreshTree();
  printStatus();
}

// ============================================================
// INTERACTIVE REPL
// ============================================================

async function interactiveLoop() {
  const rl = createInterface({
    input: process.stdin,
    output: process.stderr,
    prompt: "browse> ",
  });

  console.error("\nInteractive mode. Commands:");
  console.error("  click <id>          — click an interactive element");
  console.error("  type <id> <text>    — type text into an input");
  console.error("  submit <id>         — submit a form (by element in/near form)");
  console.error("  goto <url>          — navigate to a URL");
  console.error("  snapshot / s        — re-print the a11y tree");
  console.error("  content             — page content as markdown");
  console.error("  done                — exit\n");

  rl.prompt();

  const processLine = async (trimmed) => {
    if (!trimmed) return true;

    const parts = trimmed.split(/\s+/);
    const cmd = parts[0].toLowerCase();

    if (cmd === "done" || cmd === "exit" || cmd === "quit") {
      return false;
    } else if (cmd === "content") {
      execContent();
    } else if (cmd === "snapshot" || cmd === "s") {
      snapshot();
    } else if (cmd === "click" || cmd === "c") {
      const id = parseInt(parts[1]);
      if (isNaN(id)) {
        console.error("Usage: click <id>");
      } else {
        await execClick(id);
      }
    } else if (cmd === "type" || cmd === "t") {
      const id = parseInt(parts[1]);
      const text = parts.slice(2).join(" ");
      if (isNaN(id)) {
        console.error("Usage: type <id> <text>");
      } else {
        await execType(id, text);
      }
    } else if (cmd === "submit") {
      const id = parseInt(parts[1]);
      if (isNaN(id)) {
        console.error("Usage: submit <id>");
      } else {
        await execSubmit(id);
      }
    } else if (cmd === "goto" || cmd === "go") {
      if (!parts[1]) {
        console.error("Usage: goto <url>");
      } else {
        await execGoto(parts[1]);
      }
    } else {
      console.error(`Unknown command: ${cmd}`);
    }
    return true;
  };

  return new Promise((resolve) => {
    rl.on("line", async (line) => {
      rl.pause();
      try {
        const cont = await processLine(line.trim());
        if (!cont) {
          rl.close();
          return;
        }
      } catch (err) {
        console.error(`Error: ${err.message}`);
      }
      rl.prompt();
    });

    rl.on("close", resolve);
    rl.prompt();
  });
}

// ============================================================
// LLM AGENT LOOP (--task)
// ============================================================

const AGENT_SYSTEM = `You are a web navigation agent.
At each step, choose exactly one tool call.
Use element [id] numbers from the current accessibility tree only.
Do not rely on element IDs from previous steps.
When typing into search boxes, use submit or click the search button after.
If the page does not have what you need, navigate or search.
If the task is complete, call done with a concise summary.
Do not answer with plain text without a tool call.`;

const AGENT_TOOLS = [
  {
    type: "function",
    function: {
      name: "click",
      description: "Click an interactive element (link, button, etc.)",
      parameters: {
        type: "object",
        properties: { id: { type: "integer", description: "Element [id] from the accessibility tree" } },
        required: ["id"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "type",
      description: "Type text into an input field",
      parameters: {
        type: "object",
        properties: {
          id: { type: "integer", description: "Element [id] from the accessibility tree" },
          text: { type: "string", description: "Text to type" },
        },
        required: ["id", "text"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "submit",
      description: "Submit a form by an element inside or near the form",
      parameters: {
        type: "object",
        properties: { id: { type: "integer", description: "Element [id] from the accessibility tree" } },
        required: ["id"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "goto",
      description: "Navigate to a URL",
      parameters: {
        type: "object",
        properties: { url: { type: "string", description: "URL to navigate to" } },
        required: ["url"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "content",
      description: "Read the current page content as markdown. Use this to read articles, product details, etc.",
      parameters: { type: "object", properties: {}, required: [] },
    },
  },
  {
    type: "function",
    function: {
      name: "done",
      description: "Task is complete. Call this with a summary of what you found or did.",
      parameters: {
        type: "object",
        properties: { summary: { type: "string", description: "Summary of the result" } },
        required: ["summary"],
      },
    },
  },
];

const LLM_MODEL = process.env.OPENROUTER_MODEL;
const LLM_PROVIDER = process.env.OPENROUTER_PROVIDER || "groq";
const ACTION_HISTORY_LIMIT = Math.max(
  1,
  parseInt(process.env.AGENT_HISTORY_LIMIT || "5", 10) || 5
);

function capturePageState(tree) {
  return {
    title: doc.title || "(no title)",
    url: currentUrl,
    elements: doc.querySelectorAll("*").length,
    interactiveCount: tree?.interactiveCount ?? 0,
  };
}

function formatActionArgs(args) {
  try {
    return JSON.stringify(args || {});
  } catch {
    return "{}";
  }
}

function formatTargetLabel(node) {
  if (!node) return "";
  let label = `[${node.id}] ${node.role}`;
  if (node.name) label += ` "${node.name}"`;
  return label;
}

function summarizePageChange(before, after) {
  const parts = [];

  if (before.url === after.url) {
    parts.push(`url unchanged (${after.url})`);
  } else {
    parts.push(`url: ${before.url} -> ${after.url}`);
  }

  if (before.title === after.title) {
    parts.push(`title unchanged (${after.title})`);
  } else {
    parts.push(`title: ${JSON.stringify(before.title)} -> ${JSON.stringify(after.title)}`);
  }

  if (before.elements !== after.elements) {
    parts.push(`elements: ${before.elements} -> ${after.elements}`);
  }

  if (before.interactiveCount !== after.interactiveCount) {
    parts.push(`interactive: ${before.interactiveCount} -> ${after.interactiveCount}`);
  }

  return parts.join("; ");
}

function formatActionRecord(record, includeResult = true) {
  let line = `${record.tool} ${formatActionArgs(record.args)}`;
  if (record.targetLabel) {
    line += ` on ${record.targetLabel}`;
  }
  if (includeResult && record.resultSummary) {
    line += ` -> ${record.resultSummary}`;
  }
  return line;
}

function buildUserMessage(task, step, history, tree) {
  const page = capturePageState(tree);
  let msg = `TASK\n${task}\n\n`;
  msg += `STEP\n${step}\n\n`;
  msg += `CURRENT PAGE\n`;
  msg += `Title: ${page.title}\n`;
  msg += `URL: ${page.url}\n`;
  msg += `Elements: ${page.elements}\n`;
  msg += `Interactive: ${page.interactiveCount}\n\n`;

  if (history.length > 0) {
    const last = history[history.length - 1];
    const recent = history.slice(-ACTION_HISTORY_LIMIT);

    msg += `LAST ACTION\n${formatActionRecord(last, false)}\n\n`;
    msg += `LAST RESULT\n${last.resultSummary}\n\n`;

    if (last.outputText) {
      msg += `LAST TOOL OUTPUT\n${last.outputText}\n\n`;
    }

    msg += `RECENT ACTIONS\n`;
    for (const record of recent) {
      msg += `${record.step}. ${formatActionRecord(record)}\n`;
    }
    msg += `\n`;
  }

  msg += `CURRENT ACCESSIBILITY TREE\n`;
  for (const line of tree.lines) {
    msg += line + "\n";
  }
  return msg;
}

function sanitizeToolCall(toolCall) {
  if (!toolCall?.function?.name) return null;
  return {
    id: toolCall.id,
    type: "function",
    function: {
      name: toolCall.function.name,
      arguments: typeof toolCall.function.arguments === "string"
        ? toolCall.function.arguments
        : JSON.stringify(toolCall.function.arguments || {}),
    },
  };
}

function sanitizeMessage(message) {
  if (!message?.role) return null;

  if (message.role === "assistant") {
    const sanitized = { role: "assistant" };

    if (message.content !== undefined) {
      sanitized.content = message.content;
    }

    if (Array.isArray(message.tool_calls)) {
      const toolCalls = message.tool_calls
        .map(sanitizeToolCall)
        .filter(Boolean);
      if (toolCalls.length > 0) {
        sanitized.tool_calls = toolCalls;
      }
    }

    return sanitized;
  }

  if (message.role === "tool") {
    return {
      role: "tool",
      tool_call_id: message.tool_call_id,
      content: message.content ?? "",
    };
  }

  return {
    role: message.role,
    content: message.content ?? "",
  };
}

async function callLLM(messages) {
  const apiKey = process.env.OPENROUTER_API_KEY;

  if (!apiKey) {
    throw new Error("OPENROUTER_API_KEY not set. Add it to .env file.");
  }

  const res = await fetch("https://openrouter.ai/api/v1/chat/completions", {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      model: LLM_MODEL,
      messages: messages.map(sanitizeMessage).filter(Boolean),
      provider: {
        only: [LLM_PROVIDER],
        allow_fallbacks: false,
      },
      tools: AGENT_TOOLS,
      temperature: 0,
      max_tokens: 1024,
    }),
  });

  if (res.status === 429) {
    const retryAfter = parseFloat(res.headers.get("retry-after") || "10");
    console.error(`[agent] Rate limited. Waiting ${retryAfter}s...`);
    await new Promise(r => setTimeout(r, retryAfter * 1000));
    return callLLM(messages);
  }

  if (!res.ok) {
    const body = await res.text();
    throw new Error(`OpenRouter API error ${res.status}: ${body}`);
  }

  const data = await res.json();
  return data.choices[0].message;
}

async function agentLoop(task) {
  const maxSteps = 15;
  const actionHistory = [];

  console.error(`\n[agent] Task: ${task}`);
  console.error(`[agent] Model: ${LLM_MODEL}`);
  console.error(`[agent] Provider: ${LLM_PROVIDER} (fallbacks disabled)`);
  console.error(`[agent] Max steps: ${maxSteps}\n`);

  for (let step = 1; step <= maxSteps; step++) {
    const tree = refreshTree();
    const userMsg = buildUserMessage(task, step, actionHistory, tree);
    const requestMessages = [
      { role: "system", content: AGENT_SYSTEM },
      { role: "user", content: userMsg },
    ];

    console.error(`--- Step ${step}/${maxSteps} ---`);
    console.error(`[agent] Page: ${doc.title || currentUrl}`);
    console.error(`[agent] URL: ${currentUrl}\n`);

    const assistantMsg = await callLLM(requestMessages);

    if (assistantMsg.content) {
      console.error(`[thinking] ${assistantMsg.content}`);
    }

    const toolCalls = assistantMsg.tool_calls;
    if (!toolCalls || toolCalls.length === 0) {
      console.error("[agent] No tool call. Response:", assistantMsg.content || "(empty)");
      continue;
    }

    // Process the first tool call
    const tc = toolCalls[0];
    const fn = tc.function.name;
    let args;
    try {
      args = JSON.parse(tc.function.arguments);
    } catch {
      // Try to fix common JSON issues from LLMs (unterminated strings, etc.)
      console.error(`[agent] Malformed tool args: ${tc.function.arguments}`);
      args = {};
    }

    console.error(`[action] ${fn}(${JSON.stringify(args)})`);

    const targetNode =
      fn === "click" || fn === "type" || fn === "submit"
        ? findNode(args.id)
        : null;
    const targetLabel = formatTargetLabel(targetNode);
    const beforeState = capturePageState(tree);

    let toolResult = "";
    let resultSummary = "";
    let outputText = "";

    try {
      if (fn === "done") {
        console.log(`\nResult: ${args.summary}`);
        return;
      } else if (fn === "click") {
        await execClick(args.id);
        toolResult = `Clicked [${args.id}]. Page: "${doc.title}", URL: ${currentUrl}`;
      } else if (fn === "type") {
        await execType(args.id, args.text);
        toolResult = `Typed "${args.text}" into [${args.id}].`;
      } else if (fn === "submit") {
        await execSubmit(args.id);
        toolResult = `Submitted [${args.id}]. Page: "${doc.title}", URL: ${currentUrl}`;
      } else if (fn === "goto") {
        await execGoto(args.url);
        toolResult = `Navigated to ${currentUrl}. Page: "${doc.title}"`;
      } else if (fn === "content") {
        const md = getContentMarkdown();
        outputText = md.substring(0, 4000);
        toolResult = outputText;
        resultSummary = `returned markdown content (${outputText.length}/${md.length} chars)`;
        console.error(`[agent] Content extracted (${md.length} chars)`);
      } else {
        throw new Error(`Unsupported tool: ${fn}`);
      }
    } catch (err) {
      toolResult = `Error: ${err.message}`;
      resultSummary = `error: ${err.message}`;
      console.error(`[agent] Action error: ${err.message}`);
    }

    const afterTree = refreshTree();
    const afterState = capturePageState(afterTree);
    const pageChangeSummary = summarizePageChange(beforeState, afterState);
    if (resultSummary) {
      resultSummary = `${resultSummary}; ${pageChangeSummary}`;
    } else {
      resultSummary = pageChangeSummary;
    }

    actionHistory.push({
      step,
      tool: fn,
      args,
      targetLabel,
      resultSummary,
      outputText,
    });

    console.error(`[result] ${toolResult.substring(0, 200)}\n`);
  }

  console.error("[agent] Max steps reached. Stopping.");
}

// ============================================================
// MAIN
// ============================================================

try {
  const loadTime = await loadPage(url);

  if (flagHtml) {
    console.log(doc.documentElement?.outerHTML || "");
    dom.window.close();
    process.exit(0);
  }

  if (flagJson) {
    const tree = extractA11yTree(doc.body);
    const output = {
      url: currentUrl,
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
    dom.window.close();
    process.exit(0);
  }

  if (flagTask) {
    await agentLoop(flagTask);
  } else if (flagInteractive) {
    refreshTree();
    printStatus();
    await interactiveLoop();
  } else {
    snapshot();
  }
} catch (err) {
  console.error(`[browse] Fatal: ${err.message}`);
  process.exit(1);
}

dom.window.close();
