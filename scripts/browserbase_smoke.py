"""Plays the deployed demo in a real cloud browser (Browserbase) and saves a screenshot.

Usage:  python scripts/browserbase_smoke.py https://your-app.onrender.com
Needs BROWSERBASE_API_KEY and BROWSERBASE_PROJECT_ID in .env (or in your shell), and `pip install playwright`.
Session creation follows Browserbase's REST docs (POST /v1/sessions -> connectUrl); if it fails, the error is printed.
"""
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

if len(sys.argv) < 2:
    sys.exit("Usage: python scripts/browserbase_smoke.py https://your-app.onrender.com")
base = sys.argv[1].rstrip("/")

key, project = os.getenv("BROWSERBASE_API_KEY"), os.getenv("BROWSERBASE_PROJECT_ID")
if not key or not project:
    sys.exit("Set BROWSERBASE_API_KEY and BROWSERBASE_PROJECT_ID in .env first.")

r = httpx.post("https://api.browserbase.com/v1/sessions",
               headers={"x-bb-api-key": key}, json={"projectId": project}, timeout=30)
if r.status_code >= 400:
    sys.exit(f"Browserbase refused the session: {r.status_code} {r.text[:300]}")
connect = r.json()["connectUrl"]
print("Browserbase session started:", r.json().get("id"))

with sync_playwright() as p:
    b = p.chromium.connect_over_cdp(connect)
    page = b.contexts[0].pages[0]
    page.set_default_timeout(90000)          # a sleeping Render free service can take ~1 minute
    page.goto(base + "/play")
    page.click("text=Go: kitchen")
    page.click("text=Examine: stove")
    page.fill("#q", "Who are you?")
    page.press("#q", "Enter")
    page.wait_for_function("document.querySelector('#note').textContent.length > 0", timeout=120000)
    page.wait_for_timeout(2000)
    page.screenshot(path="smoke.png")
    print("spelled:", page.inner_text("#spelled"))
    print("note:", page.inner_text("#note"))
    b.close()
print("Saved smoke.png")