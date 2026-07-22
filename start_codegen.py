#!/usr/bin/env python3
import subprocess
import sys

try:
    from playwright.sync_api import sync_playwright
    print("Playwright found, launching codegen...")
    
    # Launch playwright codegen
    subprocess.run([sys.executable, "-m", "playwright", "codegen", "https://store.babyssb.co.jp/en"])
except ImportError:
    print("Playwright not found, please install it first with:")
    print("pip install playwright")
    print("playwright install chromium")
