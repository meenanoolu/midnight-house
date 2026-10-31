"""Plays the deployed demo in a real cloud browser (Browserbase) and saves a screenshot.

Usage: BROWSERBASE_API_KEY=... BROWSERBASE_PROJECT_ID=... python scripts/browserbase_smoke.py https://your-app.onrender.com
NOTE: session-creation shape follows Browserbase's REST docs from memory; verify with a live key.
"""
import os
import sys

import httpx
from playwright.sync_api import sync_playwright

url = sys.argv[1]
r = httpx.post("https://api.browserbase.com/v1/sessions",
               headers={"x-bb-api-key": os.environ["BROWSERBASE_API_KEY"]},
               json={"projectId": os.environ["BROWSERBASE_PROJECT_ID"]}, timeout=30)
r.raise_for_status()
connect = r.json()["connectUrl"]

with sync_playwright() as p:
    b = p.chromium.connect_over_cdp(connect)
    page = b.contexts[0].pages[0]
    page.goto(url)
    page.click("text=Go: kitchen")
    page.click("text=Examine: stove")
    page.fill("#q", "Who are you?")
    page.press("#q", "Enter")
    page.wait_for_timeout(15000)
    page.screenshot(path="smoke.png")
    print("spelled:", page.inner_text("#spelled"))
    print("note:", page.inner_text("#note"))
    b.close()
