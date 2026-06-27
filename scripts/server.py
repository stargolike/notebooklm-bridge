#!/usr/bin/env python3
"""NotebookLM persistent server — keeps browser alive between queries."""

import sys
import json
import time
import os
import signal
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

SESSION_DIR = Path.home() / ".notebooklm_session"
NOTEBOOKLM_URL = "https://notebooklm.google.com"
CMD_FILE = Path("/tmp/nblm_cmd.json")
RESULT_FILE = Path("/tmp/nblm_result.json")
LOCK_FILE = Path("/tmp/nblm.lock")
DEAD_FILE = Path("/tmp/nblm_dead")


class NotebookLMServer:
    def __init__(self):
        self.context = None
        self.page = None
        self.current_notebook = None

    def start(self):
        p = sync_playwright().start()
        self.context = p.chromium.launch_persistent_context(
            user_data_dir=str(SESSION_DIR),
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage"],
            viewport={"width": 1280, "height": 900},
        )
        self.context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => false });
        """)
        self.page = self.context.new_page()
        self._go_main()

    def _go_main(self):
        self.page.goto(NOTEBOOKLM_URL, wait_until="domcontentloaded", timeout=30000)
        self.page.wait_for_timeout(3000)

    def _find_notebook(self, name):
        search = name.lower().strip()
        links = self.page.query_selector_all('a[href*="/notebook/"][aria-labelledby]')
        for link in links:
            labelledby = link.get_attribute("aria-labelledby") or ""
            title_id = labelledby.split()[0] if labelledby else ""
            if title_id:
                try:
                    el = self.page.query_selector(f"#{title_id}")
                    if el and search in el.inner_text().strip().lower():
                        return link.get_attribute("href") or ""
                except Exception:
                    pass
        return None

    def _open_notebook(self, name):
        if self.current_notebook == name:
            return
        self._go_main()
        href = self._find_notebook(name)
        if not href:
            raise ValueError(f"Notebook '{name}' not found")
        notebook_url = NOTEBOOKLM_URL + href if href.startswith("/") else href
        self.page.goto(notebook_url, wait_until="domcontentloaded", timeout=30000)
        self.page.wait_for_timeout(3000)
        self.current_notebook = name

    def list_notebooks(self):
        self._go_main()
        self.page.wait_for_timeout(3000)
        links = self.page.query_selector_all('a[href*="/notebook/"][aria-labelledby]')
        notebooks = []
        seen = set()
        for link in links:
            labelledby = link.get_attribute("aria-labelledby") or ""
            title_id = labelledby.split()[0] if labelledby else ""
            if title_id:
                try:
                    el = self.page.query_selector(f"#{title_id}")
                    if el:
                        title = el.inner_text().strip()
                        if title and title not in seen:
                            seen.add(title)
                            notebooks.append(title)
                except Exception:
                    pass
        return notebooks

    def query(self, notebook, question):
        self._open_notebook(notebook)

        # Use JS to find, activate, and fill the chat input
        self.page.evaluate("""(q) => {
            // Find all editable elements
            const inputs = [
                ...document.querySelectorAll('div[role="textbox"]'),
                ...document.querySelectorAll('[contenteditable="true"]'),
                ...document.querySelectorAll('textarea'),
            ];

            // Prefer one that's inside a chat-like container
            let target = inputs.find(el => {
                let p = el.parentElement;
                while (p) {
                    const cls = p.className?.toString?.() || '';
                    if (/chat|message|input|prompt/i.test(cls)) return true;
                    p = p.parentElement;
                }
                return false;
            }) || inputs[0];

            if (!target) return {error: 'no input found'};

            // Try to enable it by clicking nearby chat-open buttons
            const clickables = document.querySelectorAll('button, [role="button"]');
            for (const btn of clickables) {
                const text = btn.innerText?.trim?.() || '';
                const aria = btn.getAttribute('aria-label') || '';
                if (/chat|对话/i.test(text + aria)) {
                    btn.click();
                    break;
                }
            }

            // Focus and fill
            setTimeout(() => {
                target.focus();
                // For contenteditable, use execCommand; for textarea, set value
                if (target.tagName === 'TEXTAREA' || target.tagName === 'INPUT') {
                    target.value = q;
                    target.dispatchEvent(new Event('input', {bubbles: true}));
                } else {
                    target.textContent = q;
                    target.dispatchEvent(new Event('input', {bubbles: true}));
                }
                // Press Enter
                target.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', code: 'Enter', keyCode: 13, bubbles: true}));
                target.dispatchEvent(new KeyboardEvent('keyup', {key: 'Enter', code: 'Enter', keyCode: 13, bubbles: true}));
            }, 500);

            return {ok: true};
        }""", question)

        self.page.wait_for_timeout(2000)

        # Wait for response
        self.page.wait_for_timeout(3000)
        stop_selectors = ['button[aria-label*="Stop"]', 'button:has-text("Stop")']
        for _ in range(30):
            generating = False
            for s in stop_selectors:
                try:
                    if self.page.query_selector(s):
                        generating = True
                        break
                except Exception:
                    pass
            if not generating:
                self.page.wait_for_timeout(1500)
                break
            self.page.wait_for_timeout(2000)

        # Extract
        answer = self.page.evaluate("""() => {
            const msgs = document.querySelectorAll('[class*="message"]');
            const texts = [];
            for (const m of msgs) {
                const t = m.innerText.trim();
                if (t && t.length > 30) texts.push(t);
            }
            if (texts.length === 0) return '';
            if (texts.length === 1) return texts[0];
            // Return second-to-last (AI response before user's own msg)
            return texts[texts.length - 2] || texts[texts.length - 1];
        }""")

        # Clean UI noise
        for noise in ["keep_pin", "copy_all", "thumb_up", "thumb_down", "more_vert", "more_horiz",
                       "保存到笔记", "复制", "点赞", "踩"]:
            answer = answer.replace(noise, "")
        return answer.strip()

    def sources(self, notebook):
        self._open_notebook(notebook)
        items = self.page.evaluate("""() => {
            const results = [];
            // Look for source items — typically links with pdf/url indicators or list items
            const candidates = [
                ...document.querySelectorAll('a[href*="source"]'),
                ...document.querySelectorAll('[class*="source-item"]'),
                ...document.querySelectorAll('[class*="source-card"]'),
            ];
            if (candidates.length > 0) {
                for (const el of candidates) {
                    const t = el.innerText.trim().split('\\n')[0];
                    if (t && t.length > 3 && !/^(add|thumb_up|more_vert|link|language|search)$/i.test(t))
                        results.push(t);
                }
                return results;
            }
            // Fallback: get all visible text from sidebar area
            const panels = document.querySelectorAll('[class*="sidebar"], [class*="panel"], [class*="source"]');
            const seen = new Set();
            for (const panel of panels) {
                const text = panel.innerText;
                for (const line of text.split('\\n')) {
                    const clean = line.trim();
                    if (clean && clean.length > 3 && !/^(add|thumb_up|more_vert|link|language|search|dock|create|share|settings|trending)/i.test(clean) && !seen.has(clean)) {
                        seen.add(clean);
                        results.push(clean);
                    }
                }
            }
            return results.slice(0, 30);
        }""")
        return items

    def add_url(self, notebook, url):
        self._open_notebook(notebook)
        for sel in ['button:has-text("Add source")', 'button:has-text("添加来源")']:
            try:
                btn = self.page.query_selector(sel)
                if btn and btn.is_visible():
                    btn.click()
                    self.page.wait_for_timeout(1000)
                    break
            except Exception:
                continue
        inp = self.page.query_selector('input[type="url"], input:not([type="hidden"])')
        if inp:
            inp.fill(url)
            self.page.wait_for_timeout(500)
            for s in ['button:has-text("Add")', 'button[type="submit"]']:
                try:
                    b = self.page.query_selector(s)
                    if b and b.is_visible():
                        b.click()
                        break
                except Exception:
                    pass
        self.page.wait_for_timeout(2000)
        return f"Added: {url}"

    def add_text(self, notebook, title, text):
        self._open_notebook(notebook)
        for sel in ['button:has-text("Add source")', 'button:has-text("添加来源")']:
            try:
                btn = self.page.query_selector(sel)
                if btn and btn.is_visible():
                    btn.click()
                    self.page.wait_for_timeout(1000)
                    break
            except Exception:
                continue
        # Click "pasted text" option
        for sel in ['button:has-text("Pasted text")', 'button:has-text("Text")']:
            try:
                b = self.page.query_selector(sel)
                if b and b.is_visible():
                    b.click()
                    self.page.wait_for_timeout(1000)
                    break
            except Exception:
                continue
        inp = self.page.query_selector('textarea, [contenteditable="true"]')
        if inp:
            inp.fill(f"{title}\n\n{text}")
            self.page.wait_for_timeout(500)
            for s in ['button:has-text("Insert")', 'button:has-text("Add")']:
                try:
                    b = self.page.query_selector(s)
                    if b and b.is_visible():
                        b.click()
                        break
                except Exception:
                    pass
        self.page.wait_for_timeout(2000)
        return f"Added text: {title}"

    def close(self):
        if self.context:
            self.context.close()

    def handle(self, cmd):
        action = cmd.get("action")
        if action == "list":
            return self.list_notebooks()
        elif action == "query":
            return self.query(cmd["notebook"], cmd["question"])
        elif action == "sources":
            return self.sources(cmd["notebook"])
        elif action == "add-url":
            return self.add_url(cmd["notebook"], cmd["url"])
        elif action == "add-text":
            return self.add_text(cmd["notebook"], cmd["title"], cmd["text"])
        elif action == "ping":
            return "pong"
        else:
            raise ValueError(f"Unknown action: {action}")


def main():
    if not SESSION_DIR.exists():
        print("No session. Run login.py first.")
        sys.exit(1)

    if LOCK_FILE.exists():
        print("Server already running.")
        sys.exit(0)

    LOCK_FILE.write_text(str(os.getpid()))
    CMD_FILE.unlink(missing_ok=True)
    RESULT_FILE.unlink(missing_ok=True)
    DEAD_FILE.unlink(missing_ok=True)

    server = NotebookLMServer()
    try:
        server.start()
    except Exception as e:
        LOCK_FILE.unlink(missing_ok=True)
        DEAD_FILE.write_text(str(e))
        sys.exit(1)

    try:
        while True:
            if CMD_FILE.exists():
                try:
                    cmd = json.loads(CMD_FILE.read_text())
                    CMD_FILE.unlink()
                    result = server.handle(cmd)
                    RESULT_FILE.write_text(json.dumps({"ok": True, "data": result}, ensure_ascii=False))
                except Exception as e:
                    RESULT_FILE.write_text(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
                    CMD_FILE.unlink(missing_ok=True)
            time.sleep(0.3)
    except KeyboardInterrupt:
        pass
    finally:
        server.close()
        LOCK_FILE.unlink(missing_ok=True)
        RESULT_FILE.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
