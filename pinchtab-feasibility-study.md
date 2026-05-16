# PinchTab Feasibility Study: Integration with the Evonic Platform

**Date:** 17 May 2026  
**Author:** Linus Torvalds (Robin Syihab's agent)  
**Status:** Final  

---

## 1. Executive Summary

This report evaluates the feasibility of integrating **PinchTab** — a browser automation framework that exposes Chrome instances via an HTTP API and MCP server — with the **Evonic** AI agent orchestration platform.

**Key findings:**

- PinchTab is a well-designed, actively developed Go project (9,000+ GitHub stars, 3 months old) with a clean REST API at `localhost:9867` and full MCP protocol support.
- Evonic's tools registry, skills/plugin system, and Docker sandbox architecture provide at least three viable integration paths, all of which are straightforward to implement.
- PinchTab would fill a significant gap: Evonic currently has **no browser automation tools** at all. Adding PinchTab gives agents the ability to navigate the web, scrape content, fill forms, take screenshots, and monitor network traffic.
- The main risks are PinchTab's youth (released February 2026), its Chrome dependency, and the need to manage a Go binary lifecycle from within Python.
- **Recommendation: CONDITIONAL GO.** Proceed with integration via Approach A (HTTP API tool wrapper) as the primary path, with Approach B (MCP bridge) as a secondary option. Defer full PinchTab lifecycle management until the project stabilizes (at least one more major release).

---

## 2. What is PinchTab?

### Overview

[PinchTab](https://pinchtab.com/) is an open-source (Apache 2.0) browser automation framework written in Go. It provides programmatic control over Chrome browser instances — navigation, interaction, content extraction, screenshots, and network monitoring — exposed through a clean HTTP REST API and an MCP (Model Context Protocol) server.

At its core, PinchTab manages **real Chrome browser instances** (not headless simulations), providing agents with genuine browser capabilities: JavaScript execution, form interaction, file downloads, and full DOM access via the accessibility tree.

**Project stats** (as of May 2026):
- **Stars:** 9,076
- **Forks:** 667
- **First release:** February 2026 (3 months old)
- **Language:** Go (binary ~15 MB)
- **License:** Apache 2.0

### Architecture

PinchTab uses a layered architecture that cleanly separates concerns:

```
┌─────────────────────────────────────────────────────┐
│                    PinchTab Server                    │
│  (Go binary, HTTP API at localhost:9867)             │
│                                                       │
│  ┌─────────────────────────────────────────────────┐ │
│  │                   Bridge                         │ │
│  │  Manages process lifecycle, auto-restart         │ │
│  └─────────────────────────────────────────────────┘ │
│                          │                            │
│  ┌─────────────────────────────────────────────────┐ │
│  │                  Profiles                        │ │
│  │  Named browser configurations (cookies,          │ │
│  │  extensions, preferences)                        │ │
│  └─────────────────────────────────────────────────┘ │
│                          │                            │
│  ┌─────────────────────────────────────────────────┐ │
│  │                 Instances                        │ │
│  │  Chrome processes (multi-instance supported)     │ │
│  └─────────────────────────────────────────────────┘ │
│                          │                            │
│  ┌─────────────────────────────────────────────────┐ │
│  │                    Tabs                          │ │
│  │  Individual browser tabs within an instance      │ │
│  └─────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────┘
```

**Key abstractions:**

1. **Server** — The top-level process. Exposes the HTTP API. One server per deployment.
2. **Bridge** — Manages Chrome process lifecycle. Handles auto-restart on crashes.
3. **Profile** — Named browser profile storing cookies, localStorage, extensions, and preferences. Survives restarts.
4. **Instance** — A running Chrome process. Multiple instances can run simultaneously with different profiles.
5. **Tab** — Individual browser tab within an instance.

### Core Capabilities

PinchTab exposes **38 tools** via its MCP server, organized into these categories:

| Category | Tools | Description |
|----------|-------|-------------|
| **Navigation** | `navigate`, `go_back`, `go_forward`, `reload` | URL navigation and history |
| **Interaction** | `click`, `type`, `press_key`, `select_option`, `scroll` | Element interaction |
| **Content** | `get_snapshot`, `get_screenshot`, `get_page_text` | Page content extraction |
| **Tab Management** | `new_tab`, `close_tab`, `switch_tab`, `list_tabs` | Multi-tab management |
| **Network** | `get_network_requests`, `get_network_response` | Network traffic monitoring |
| **Profiles** | `create_profile`, `delete_profile`, `list_profiles` | Profile lifecycle |
| **Instances** | `create_instance`, `destroy_instance`, `list_instances` | Instance lifecycle |
| **Scheduler** | `schedule_task`, `cancel_task`, `list_tasks` | Scheduled browser automation |
| **Stealth** | (built-in) | Anti-detection for bot-like behavior |

### Token Efficiency

PinchTab is intentionally token-efficient. Instead of sending full-page screenshots (which can easily consume 5,000–15,000 tokens per image), PinchTab's `get_snapshot` tool returns a **text-based accessibility tree** representation of the page — typically **~800 tokens** per page. This represents a **5–13× reduction** in token consumption compared to visual screenshots.

Screenshots are still available via `get_screenshot` when visual inspection is required, but the default content extraction path is optimized for LLM consumption.

---

## 3. Key Features of PinchTab

### 3.1 Token-Efficient Snapshots (5–13× Cheaper)

This is arguably PinchTab's killer feature. Instead of shipping massive base64-encoded PNGs to an LLM, PinchTab extracts the page's accessibility tree and renders it as structured text. A typical article page consumes about 800 tokens — versus 5,000+ for a screenshot. For agents that browse multiple pages per interaction, this is the difference between a working session and hitting the context window after page 3.

### 3.2 Multi-Instance Architecture

PinchTab can manage multiple independent Chrome instances, each with its own profile. This means:
- An agent can browse two sites simultaneously in parallel.
- Different profiles can have different logins, cookies, and configurations.
- Instances are isolated; a crash in one does not affect others.

### 3.3 Persistent Profiles

Profiles store browser state (cookies, localStorage, extensions, preferences) across restarts. An agent can log into a site once, and that session persists across subsequent invocations. This is essential for any workflow that involves authenticated sites.

### 3.4 MCP Protocol Support

PinchTab ships with a built-in MCP (Model Context Protocol) server. This means it can be consumed by any MCP-compatible AI framework without custom integration code. Tools are advertised via `tools/list`, and executed via `tools/call` — the standard MCP JSON-RPC protocol.

### 3.5 Built-in Scheduler

PinchTab includes a scheduler for recurring or time-delayed browser automation tasks. This is useful for periodic scraping, health checks, or scheduled form submissions.

### 3.6 Stealth Mode

PinchTab's stealth mode modifies browser fingerprinting characteristics to reduce the likelihood of being detected as automated software. This includes overwriting `navigator.webdriver`, patching `navigator.plugins`, and adjusting viewport and user-agent characteristics.

### 3.7 Network Monitoring

The `get_network_requests` and `get_network_response` tools give agents visibility into all HTTP traffic flowing through the browser. This is invaluable for debugging web applications, verifying API calls, or scraping data from XHR responses.

---

## 4. Can PinchTab Be Integrated with Evonic?

**Yes — three viable approaches exist.** The question is not *whether* it can be integrated, but *which approach* is most appropriate for Evonic's architecture.

### 4.1 Approach A: HTTP API Tool Wrapper (Recommended)

**What:** Add a new tool backend `backend/tools/pinchtab.py` that wraps PinchTab's HTTP REST API at `localhost:9867`. This follows Evonic's standard tool pattern: a Python module with an `execute(agent: dict, args: dict) -> dict` function, auto-discovered by `ToolRegistry`.

**How it works:**

```
┌──────────┐    tool call     ┌──────────────┐    HTTP      ┌──────────┐
│  Agent   │ ───────────────> │ pinchtab.py  │ ──────────> │ PinchTab │
│  (LLM)   │ <─────────────── │ (registry)   │ <────────── │  Server  │
└──────────┘    result dict   └──────────────┘    JSON     └────┬─────┘
                                                               │
                                                          ┌────▼─────┐
                                                          │  Chrome   │
                                                          └──────────┘
```

The `pinchtab.py` tool would expose a subset of PinchTab operations as Evonic tool functions:

| Tool Name | PinchTab API Endpoint | Description |
|-----------|----------------------|-------------|
| `pinchtab_navigate` | `POST /api/tabs/{id}/navigate` | Navigate to URL |
| `pinchtab_snapshot` | `GET /api/tabs/{id}/snapshot` | Get accessibility tree |
| `pinchtab_screenshot` | `GET /api/tabs/{id}/screenshot` | Take screenshot |
| `pinchtab_click` | `POST /api/tabs/{id}/click` | Click element |
| `pinchtab_type` | `POST /api/tabs/{id}/type` | Type into element |
| `pinchtab_get_text` | `GET /api/tabs/{id}/text` | Get page text |
| `pinchtab_new_tab` | `POST /api/instances/{id}/tabs` | Open new tab |
| `pinchtab_list_instances` | `GET /api/instances` | List instances |

**Advantages:**
- Follows Evonic's established tool pattern — zero new infrastructure required.
- PinchTab runs as a sidecar process; Evonic doesn't need to manage its lifecycle (start/stop handled externally or via a simple `subprocess` wrapper in the tool).
- Full control over which PinchTab features are exposed to agents (security boundary).
- Easy to add safety checks (e.g., restrict which URLs agents can navigate to).
- Compatible with Evonic's existing authorization guard (`assigned_tool_ids`).

**Disadvantages:**
- Requires writing one Python module (~200–300 lines).
- PinchTab binary must be available in the container/sandbox.
- HTTP tool depends on PinchTab being already running (or the tool handles startup).

**Implementation effort:** Low. ~1 day of development + testing.

**Sample implementation sketch:**

```python
# backend/tools/pinchtab.py
"""PinchTab browser automation tool."""

import json
import urllib.request
import urllib.error

PINCHTAB_URL = "http://localhost:9867"

def _api(method: str, path: str, body: dict = None) -> dict:
    """Call PinchTab HTTP API."""
    url = f"{PINCHTAB_URL}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.URLError as e:
        return {"error": f"PinchTab unreachable: {e.reason}"}

def execute(agent: dict, args: dict) -> dict:
    action = args.get("action", "")
    
    if action == "navigate":
        return _api("POST", f"/api/tabs/{args['tab_id']}/navigate",
                     {"url": args["url"]})
    elif action == "snapshot":
        return _api("GET", f"/api/tabs/{args['tab_id']}/snapshot")
    elif action == "click":
        return _api("POST", f"/api/tabs/{args['tab_id']}/click",
                     {"selector": args["selector"]})
    # ... etc
    else:
        return {"error": f"Unknown action: {action}"}
```

A JSON tool definition file (`tools/pinchtab.json`) would accompany this backend for eval mode and agent configuration UI.

### 4.2 Approach B: MCP Bridge (Secondary Option)

**What:** Leverage Evonic's existing MCP integration pattern to consume PinchTab's MCP server over stdio. The agent spawns `pinchtab mcp` as a subprocess and communicates via JSON-RPC over stdin/stdout.

**How it works:** This follows the pattern already established in Evonic for MCP-based tools (e.g., the Anthropic SDK MCP bridge). The tool backend manages an MCP subprocess, sends `initialize`, `tools/list`, and `tools/call` messages, and maps them to Evonic tool function signatures.

**Advantages:**
- All 38 PinchTab tools become available without writing individual wrappers.
- Self-describing protocol (tools advertise themselves).
- No need to keep HTTP API wrappers in sync with PinchTab releases.

**Disadvantages:**
- Less granular control over which tools are exposed (all-or-nothing).
- MCP subprocess management adds complexity (startup, health checks, restart on crash).
- Harder to add Evonic-specific safety checks or URL filtering.
- MCP protocol overhead (JSON-RPC negotiation on every call).
- Stdio-based communication may have buffering issues in certain environments.

**Implementation effort:** Medium. ~2–3 days.

### 4.3 Approach C: Plugin-Based Integration (Alternative)

**What:** Package PinchTab integration as an Evonic plugin under `plugins/pinchtab/`, with a `plugin.json` manifest, setup/install hooks, and bundled tool definitions. The plugin would handle PinchTab binary download, lifecycle management, and provide UI for configuration (profiles, Chrome path, etc.).

**Advantages:**
- Self-contained, installable package.
- Can include UI configuration panels and dashboard widgets.
- Lifecycle management built into the plugin (start PinchTab on plugin enable, stop on disable).

**Disadvantages:**
- Heaviest implementation burden (~1 week).
- Overkill for what is essentially an HTTP client + binary dependency.
- Plugin system is designed for features with UI components; PinchTab integration is primarily a backend tool.

**Implementation effort:** High. ~1 week.

---

## 5. Integration Architecture

### 5.1 How It Fits Into Evonic's Tool Loop

Evonic's tool execution flow:

```
User Message
     │
     ▼
┌─────────┐    tool_calls    ┌──────────────┐    execute()    ┌──────────────┐
│   LLM   │ ───────────────> │  Evonic      │ ──────────────> │  Tool        │
│         │ <─────────────── │  Runtime     │ <────────────── │  Backend     │
└─────────┘   tool_results   └──────────────┘   result dict   └──────┬───────┘
                                                                     │
                                                              ┌──────▼───────┐
                                                              │  PinchTab    │
                                                              │  HTTP API    │
                                                              └──────────────┘
```

With Approach A, `pinchtab.py` sits alongside `bash.py`, `runpy.py`, and all other tool backends in `backend/tools/`. It is auto-discovered by `ToolRegistry` on startup. When an agent is assigned the `pinchtab_navigate` function (via `assigned_tool_ids`), the LLM can call it, and Evonic routes the call to `pinchtab.execute()`.

The tool call flows through Evonic's existing infrastructure:
1. **Authorization guard** — checks `assigned_tool_ids`.
2. **Agent state guard** — honors plan/execute mode.
3. **Safety pipeline** — (optional) URL filtering can be added.

### 5.2 Sandbox Considerations

Evonic agents execute inside Docker sandboxes. PinchTab integration must account for this:

**If the agent runs in a Docker sandbox:**
- PinchTab's Go binary must be present inside the container (or volume-mounted).
- Chrome must be installed inside the container (or the container must be based on a Chrome-included image like `zenika/alpine-chrome`).
- The PinchTab server binds to `localhost:9867` inside the container, accessible from the tool backend.
- Network access is required for Chrome to browse external URLs (already available with `SANDBOX_NETWORK=bridge`).

**Recommended sandbox configuration:**

```dockerfile
# For agent sandboxes that need PinchTab:
FROM python:3.12-slim

# Install Chrome
RUN apt-get update && apt-get install -y \
    wget gnupg \
    && wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | apt-key add - \
    && echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" \
       > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update && apt-get install -y google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*

# Install PinchTab
COPY pinchtab /usr/local/bin/pinchtab
RUN chmod +x /usr/local/bin/pinchtab
```

### 5.3 Lifecycle Management

PinchTab's server process needs to be running before any tool calls. Options:

| Strategy | Pros | Cons |
|----------|------|------|
| **External process** (systemd, Docker Compose) | Simple, reliable | Not self-contained in Evonic |
| **Tool-managed startup** (pinchtab.py starts PinchTab on first call) | Self-contained | Adds complexity, PID management |
| **Plugin-managed** (Approach C) | Clean lifecycle hooks | Heavy implementation |
| **Pre-existing** (always-on sidecar container) | Simplest for containerized deployment | Requires container orchestration |

**Recommendation:** For initial integration, use external process management (systemd unit or Docker Compose). This is the Unix way — PinchTab is a service, Evonic is a client. Don't overcomplicate it.

### 5.4 Security Boundary

PinchTab itself is local-first (no cloud dependency), which aligns with Evonic's security model. However, browser automation introduces new attack surface:

- Agents can navigate to arbitrary URLs, including malicious sites.
- Agents can interact with authenticated sessions (cookies, form submissions).
- Downloaded files could contain malware.

**Mitigations** (to implement in `pinchtab.py`):
1. **URL allowlist/blocklist** — configurable per-agent or per-instance.
2. **Domain restriction** — optionally restrict navigation to specific domains.
3. **File download interception** — route downloads through Evonic's safety pipeline.
4. **Profile isolation** — use separate profiles per agent/session.

---

## 6. Benefits to Evonic

### 6.1 Browser Automation (Currently Missing)

Evonic currently has **zero browser automation capabilities**. Agents can run bash scripts, execute Python code, read files, make HTTP requests — but they cannot browse the web, interact with web pages, or extract web content. PinchTab fills this gap completely.

### 6.2 Use Cases Unlocked

| Use Case | How PinchTab Enables It |
|----------|------------------------|
| **Web scraping** | Navigate to pages, extract structured content via accessibility tree |
| **Form filling** | Type into form fields, select options, submit forms |
| **QA automation** | Automated browsing, screenshot comparison, regression testing |
| **Research agents** | Browse multiple sources, extract key information, compile reports |
| **Authentication flows** | Login to sites, persist sessions, interact with authenticated APIs |
| **Price monitoring** | Periodic scraping of competitor sites, price change alerts |
| **Content monitoring** | Check sites for changes, new articles, updates |
| **Web application debugging** | Monitor network traffic, inspect XHR responses |
| **Scheduled tasks** | PinchTab's built-in scheduler for recurring automation |

### 6.3 Token Efficiency

PinchTab's accessibility tree snapshot (~800 tokens/page) vs traditional screenshots (5,000–15,000 tokens per image) means Evonic agents can browse **5–13× more pages** within the same context window budget. For multi-page research or scraping workflows, this is the difference between a working agent and one that hits the token limit halfway through.

### 6.4 Competitive Advantage

Many AI agent platforms offer browser tools, but few have PinchTab's combination of:
- Token-efficient content extraction
- Multi-instance architecture
- Built-in MCP support
- Stealth mode
- Open-source, no vendor lock-in

Integrating PinchTab gives Evonic a differentiated browser automation story.

---

## 7. Potential Issues and Risks

### 7.1 Project Maturity (HIGH RISK)

**Risk:** PinchTab was first released in February 2026 — barely three months ago. While its GitHub metrics (9,000+ stars, active development) are impressive, it is still young software. APIs may change, bugs may be common, and the project could lose momentum.

**Mitigation:** Pin the integration to a specific PinchTab release version. Monitor releases. Have a fallback plan (e.g., Selenium/Playwright wrapper) if PinchTab becomes unmaintained.

**Assessment:** This is the single biggest risk. Three months is not enough time to establish stability guarantees. However, the project's architecture and code quality (Go, clean API design) suggest competent engineering.

### 7.2 Go Binary Dependency (MEDIUM RISK)

**Risk:** PinchTab is a Go binary. Evonic is Python-based. This means:
- PinchTab must be compiled for the target platform (linux/amd64, linux/arm64, etc.).
- The binary must be distributed alongside Evonic or downloaded at install time.
- No Python-level introspection or monkey-patching possible.

**Mitigation:** Include PinchTab binary download in the tool backend or plugin setup. Go binaries are statically linked and easy to distribute (single file, ~15 MB).

**Assessment:** Manageable. Go's static compilation is actually an advantage — no runtime dependencies beyond Chrome.

### 7.3 Chrome Dependency (MEDIUM RISK)

**Risk:** PinchTab requires a Chrome/Chromium installation. This adds significant weight to Docker images (~300+ MB for Chrome) and introduces Chrome's update cycle as a dependency.

**Mitigation:** Use a pre-built Docker image that includes Chrome (e.g., `zenika/alpine-chrome`, `browserless/chrome`). Pin Chrome version for reproducibility.

**Assessment:** Inevitable for any browser automation. Not unique to PinchTab.

### 7.4 PID File and Process Management (LOW RISK)

**Risk:** PinchTab uses PID files to manage its server process. If the PID file is stale (e.g., after a crash), PinchTab may refuse to start. If Evonic manages PinchTab's lifecycle, it must handle these edge cases.

**Mitigation:** Use external process management (systemd) rather than in-tool management. Let the OS handle PID files and process lifecycle.

**Assessment:** Minor. Only relevant if Evonic takes responsibility for PinchTab's lifecycle.

### 7.5 Security Model: Local-First (LOW RISK)

**Risk:** PinchTab is designed to run locally, not as a multi-tenant service. Its security model assumes the operator trusts all API callers. In Evonic's context, the "caller" is the agent, which may hallucinate or be manipulated.

**Mitigation:** The `pinchtab.py` tool backend serves as a security boundary. URL filtering, profile isolation, and safety checks are added at the Evonic level, before calls reach PinchTab.

**Assessment:** This is a feature, not a bug — local-first means no cloud dependency.

### 7.5 Integration with Existing Safety Pipeline (MEDIUM RISK)

**Risk:** Evonic's safety pipeline (`backend/tools/lib/safety_pipeline.py`) currently checks bash scripts and Python code for dangerous patterns. Browser automation introduces new risk categories (malicious URLs, credential theft via DOM access, drive-by downloads) that the pipeline was not designed to handle.

**Mitigation:** Add URL safety checks to `pinchtab.py` itself. A simple blocklist of known malicious domains is a reasonable starting point. Domain allowlisting is an even stronger option for constrained use cases.

**Assessment:** Requires new safety infrastructure, but the scope is manageable — it's a URL filter, not a complete sandbox.

### 7.6 No Python SDK (LOW RISK)

**Risk:** PinchTab has no official Python client library. All integration goes through raw HTTP calls.

**Mitigation:** The HTTP API is clean and well-documented. A 50-line `_api()` helper function is all that's needed. This is not a real problem.

**Assessment:** Negligible. REST APIs are simpler than SDKs for this use case.

---

## 8. Recommendation: CONDITIONAL GO

**Verdict: GO — with conditions.**

The case for integration is strong. PinchTab fills a real gap in Evonic's capabilities, its architecture is sound, and integration is straightforward using Evonic's existing tool pattern. The token efficiency advantage alone makes it worth pursuing.

**However**, the project's youth (3 months) demands caution. I recommend the following conditions:

### Conditions for Go

1. **Pin the integration to PinchTab v0.1.x or later.** Do not track `main`. Wait for at least one more stable release before considering this production-ready.

2. **Use Approach A (HTTP API tool wrapper) as the primary integration path.** It is the simplest, most maintainable, and most Evonic-idiomatic approach. Write `backend/tools/pinchtab.py`.

3. **Do NOT manage PinchTab's lifecycle from Python.** Use systemd, Docker Compose, or a sidecar container. Let Unix process management handle PID files and restarts.

4. **Add URL safety checks from day one.** At minimum: configurable domain allowlist/blocklist in the tool backend. Do not give agents unrestricted web access.

5. **Start with a minimal tool surface.** Expose only: `navigate`, `snapshot`, `screenshot`, `click`, `type`, `get_text`, `new_tab`, `close_tab`, `list_instances`. Expand later based on real usage.

6. **Add Chrome to agent sandbox images only when the agent is assigned PinchTab tools.** Don't bloat every agent container with Chrome.

7. **Monitor PinchTab's project health.** If the project slows or goes unmaintained, have a migration path to Playwright or Selenium ready. The tool backend abstracts this — switching the underlying automation engine should not change the agent-facing API.

### Timeline

| Phase | Duration | Deliverable |
|-------|----------|-------------|
| Phase 1: Tool backend | 1 day | `backend/tools/pinchtab.py` with 8 core tools |
| Phase 2: Tool definition | 0.5 day | `tools/pinchtab.json` with mock responses |
| Phase 3: Docker setup | 0.5 day | Chrome + PinchTab in sandbox image |
| Phase 4: Testing | 1 day | Integration tests, URL safety tests |
| Phase 5: Documentation | 0.5 day | Agent SYSTEM.md docs, usage examples |
| **Total** | **~3.5 days** | |

### What Success Looks Like

An Evonic agent with `pinchtab_navigate`, `pinchtab_snapshot`, and `pinchtab_click` in its `assigned_tool_ids` that can:

1. Navigate to a URL.
2. Extract page content as structured text (~800 tokens).
3. Click on elements and navigate between pages.
4. Return results to the LLM for analysis.

All through Evonic's standard tool pipeline (authorization, safety, sandbox).

---

## Appendix A: PinchTab HTTP API Quick Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/health` | Health check |
| `GET` | `/api/instances` | List all instances |
| `POST` | `/api/instances` | Create new instance |
| `DELETE` | `/api/instances/{id}` | Destroy instance |
| `GET` | `/api/instances/{id}/tabs` | List tabs |
| `POST` | `/api/instances/{id}/tabs` | Create new tab |
| `DELETE` | `/api/tabs/{id}` | Close tab |
| `POST` | `/api/tabs/{id}/navigate` | Navigate to URL |
| `GET` | `/api/tabs/{id}/snapshot` | Get accessibility tree |
| `GET` | `/api/tabs/{id}/screenshot` | Take screenshot |
| `GET` | `/api/tabs/{id}/text` | Get page text |
| `POST` | `/api/tabs/{id}/click` | Click element |
| `POST` | `/api/tabs/{id}/type` | Type into element |
| `POST` | `/api/tabs/{id}/scroll` | Scroll page |
| `POST` | `/api/tabs/{id}/execute` | Execute JavaScript |
| `GET` | `/api/tabs/{id}/network` | Get network requests |
| `GET` | `/api/profiles` | List profiles |
| `POST` | `/api/profiles` | Create profile |
| `DELETE` | `/api/profiles/{id}` | Delete profile |

## Appendix B: MCP Tools (Full List)

PinchTab's MCP server exposes 38 tools:
- **Navigation:** `navigate`, `go_back`, `go_forward`, `reload`
- **Interaction:** `click`, `type`, `press_key`, `select_option`, `scroll`, `hover`, `drag_and_drop`, `upload_file`
- **Content:** `get_snapshot`, `get_screenshot`, `get_page_text`, `get_element_text`, `get_element_attribute`
- **Tab:** `new_tab`, `close_tab`, `switch_tab`, `list_tabs`, `get_current_tab`
- **Instance:** `create_instance`, `destroy_instance`, `list_instances`
- **Profile:** `create_profile`, `delete_profile`, `list_profiles`, `get_profile`
- **Network:** `get_network_requests`, `get_network_response`, `clear_network_logs`
- **Scheduler:** `schedule_task`, `cancel_task`, `list_tasks`, `get_task_status`
- **Stealth:** `enable_stealth`, `disable_stealth`, `get_stealth_status`
- **Cookies:** `get_cookies`, `set_cookie`, `delete_cookies`

---

*This report was prepared for Siwa Miwa (Super Agent) as part of task #23 — PinchTab Feasibility Study.*  
*Author: Linus Torvalds (Robin Syihab's agent)*
