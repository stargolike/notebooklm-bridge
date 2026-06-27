---
name: notebooklm-bridge
description: "Query Google NotebookLM knowledge bases from the CLI via a persistent Playwright browser. Use this skill when the user wants to read their NotebookLM notebooks, query knowledge bases, search sources, list notebooks, or add content to NotebookLM. Trigger on mentions of 'notebooklm', 'notebook', '知识库', '笔记本', 'notebook lm', or requests like 'check my notebook', 'query my knowledge base', 'what does my notebook say about...', 'add to notebook'."
---

# NotebookLM Bridge

Connect to Google NotebookLM via Playwright — server keeps browser alive between queries.

## Prerequisites

```bash
pip install playwright && python -m playwright install chromium
```

## First-Time Login

Run once with a display:

```bash
python scripts/login.py
```

For headless cloud servers, copy session from a machine that has logged in:

```bash
scp -r ~/.notebooklm_session user@server:~/
```

## Core Commands

All operations use `scripts/nblm`. The server auto-starts on first call and stays alive — a single browser handles all requests.

```bash
python scripts/nblm list                          # List all notebooks
python scripts/nblm query "<name>" "<question>"   # Query a notebook
python scripts/nblm sources "<name>"              # List sources
python scripts/nblm add-url "<name>" "<url>"      # Add URL source
python scripts/nblm add-text "<name>" "<title>" "<text>"  # Add text source
python scripts/nblm server-stop                   # Stop background server
```

## How to Operate

When the user's request matches this skill's description:

- Silently run the appropriate `nblm` command. Do NOT explain what command you're running.
- Show only the result. If it's a list/query answer, present it directly.
- If query response is long, show it in full — the user wants the complete answer.
- If a notebook name doesn't match exactly, run `list` first to find the correct name.
- If the server died (error about `/tmp/nblm.lock`), delete lock files and retry:
  ```bash
  rm -f /tmp/nblm.lock /tmp/nblm_cmd.json /tmp/nblm_result.json
  ```

## Architecture

```
nblm (client) ──writes──▶ /tmp/nblm_cmd.json
                          scripts/server.py (persistent Playwright browser)
                          ◀──reads── /tmp/nblm_result.json
```

Scripts are executed, never read into context — zero token cost.
