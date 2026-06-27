# NotebookLM Bridge for OpenCode

Query [Google NotebookLM](https://notebooklm.google.com) from opencode via a persistent Playwright browser.

## Install

```bash
pip install playwright
python -m playwright install chromium
```

## Setup

```bash
# Login (needs a display, one-time)
python scripts/login.py
```

For headless cloud servers, copy the session:
```bash
scp -r ~/.notebooklm_session user@server:~/
```

## Usage

```bash
python scripts/nblm list                           # List notebooks
python scripts/nblm query "My NB" "Question"       # Query
python scripts/nblm sources "My NB"                # List sources
python scripts/nblm add-url "My NB" "https://..."  # Add URL
python scripts/nblm add-text "My NB" "Title" "Text"
python scripts/nblm server-stop                    # Stop server
```

Server auto-starts on first call. Browser stays alive between queries.

## How it works

```
nblm (client) ──▶ /tmp/nblm_cmd.json
                  server.py (Playwright browser)
                  ◀── /tmp/nblm_result.json
```

## License

MIT
