# Stagehand Chrome Extension Setup

Complete guide to running Stagehand with your local Chrome browser using the extension mode.

## Overview

Extension mode allows Stagehand to control your **existing Chrome browser** instead of launching a new browser instance. This is perfect for enterprise environments where users need automation in their own browser with existing sessions, cookies, and extensions.

## Architecture

```
┌──────────────────┐
│  Your Python     │
│  Script          │
│  (Stagehand)     │
└────────┬─────────┘
         │ WebSocket
         ↓
┌──────────────────┐
│  Extension       │
│  Server          │
│  (localhost:8766)│
└────────┬─────────┘
         │ WebSocket
         ↓
┌──────────────────┐
│  Chrome          │
│  Extension       │
│  (Background)    │
└────────┬─────────┘
         │ CDP + chrome.debugger
         ↓
┌──────────────────┐
│  Your Chrome     │
│  Browser Tab     │
└──────────────────┘
```

## Prerequisites

- Python 3.10 or higher
- Google Chrome or Chromium browser
- pip (Python package manager)

## Installation Steps

### Step 1: Install Server Dependencies

```bash
cd server
pip install -r requirements.txt
```

### Step 2: Load Chrome Extension

1. Open Chrome and go to `chrome://extensions/`

2. Enable **Developer mode** (toggle in top-right corner)

3. Click **"Load unpacked"**

4. Navigate to and select the `chrome_extension/` directory in this repository

5. You should see "Stagehand Extension Bridge" appear in your extensions list

6. **Important**: The extension will show a warning that it "has started debugging this browser". This is normal and required for CDP access.

7. (Optional) Pin the extension to your toolbar for easy access to the status popup

### Step 3: Start the WebSocket Server

Open a terminal and run:

```bash
cd server
python extension_server.py
```

You should see:

```
[2025-10-07 13:00:00] INFO - Starting Stagehand Extension Server...
[2025-10-07 13:00:00] INFO - Extension will connect to: ws://localhost:8766
[2025-10-07 13:00:00] INFO - Python clients connect to: ws://localhost:8766
[2025-10-07 13:00:00] INFO - ✅ Server running on ws://localhost:8766
```

### Step 4: Verify Extension Connection

1. Click on the Stagehand extension icon in Chrome

2. The popup should show:
   - ✅ Connected to Python server
   - Status: Connected

If you see "Server not running", make sure the server from Step 3 is running.

### Step 5: Install Stagehand Python (if not already installed)

```bash
pip install stagehand
# OR for development
pip install -e .
```

## Usage

### Basic Example

Create a file `test_extension.py`:

```python
import asyncio
from stagehand import Stagehand

async def main():
    # Connect to your Chrome browser via extension
    async with Stagehand(env="EXTENSION") as stagehand:
        page = stagehand.page

        # Navigate to a URL
        await page.goto("https://ycombinator.com")

        # Use AI to interact
        result = await page.act("click on the Browserbase link")
        print(f"Action result: {result}")

        # Extract data
        companies = await page.extract(
            "Extract names of first 5 companies in batch 3"
        )
        print(f"Extracted: {companies}")

if __name__ == "__main__":
    asyncio.run(main())
```

Run it:

```bash
python test_extension.py
```

### What Happens:

1. Your Python script connects to the WebSocket server
2. Server routes commands to the Chrome extension
3. Extension attaches to your active Chrome tab using `chrome.debugger`
4. All Stagehand AI features (`act`, `observe`, `extract`, `agent`) work normally!
5. Actions happen in **your actual Chrome browser tab**

## Troubleshooting

### "Chrome extension not connected to server"

**Solution**: Make sure the extension is loaded in Chrome. Open `chrome://extensions/` and verify "Stagehand Extension Bridge" is enabled.

### "No active tab found"

**Solution**: Make sure you have at least one Chrome tab open before running your Python script.

### "Debugger already attached"

**Solution**: Chrome only allows one debugger at a time. Close any other tools using Chrome DevTools Protocol:
- Chrome DevTools (F12)
- Other automation tools (Puppeteer, Playwright, Selenium)
- Other Stagehand sessions

### "WebSocket connection failed"

**Solution**:
1. Verify the server is running: `python server/extension_server.py`
2. Check if port 8766 is available: `lsof -i :8766`
3. Try restarting the server

### Extension shows "Debugging this browser"

**Status**: This is **normal and expected**! The extension needs `chrome.debugger` permission to access CDP. This warning will persist while the extension is loaded.

For enterprise deployments, IT admins can force-install the extension via Chrome Policy to reduce user friction.

### Page actions are slower than LOCAL mode

**Status**: This is normal. Extension mode adds WebSocket routing overhead. Typical overhead is 50-200ms per command. For production automation, consider using BROWSERBASE or LOCAL mode.

## Features Supported

✅ **Fully Supported**:
- `page.goto()` - Navigation
- `page.act()` - AI actions
- `page.observe()` - AI observations
- `page.extract()` - AI data extraction
- `page.evaluate()` - JavaScript execution
- CDP commands - Full access via `chrome.debugger`
- Cookies - Via `chrome.cookies` API
- Multiple tabs - Switch between tabs

⚠️ **Limited**:
- Downloads - Goes to user's download folder (can't customize path)
- File uploads - Requires user interaction

❌ **Not Supported**:
- Browser launch options - Uses existing Chrome
- Headless mode - Uses visible Chrome
- Multiple browser contexts - Single Chrome instance

## Stopping

1. **Stop your Python script**: Ctrl+C or let it complete
2. **Stop the server**: Ctrl+C in the server terminal
3. **Unload extension** (optional): Go to `chrome://extensions/` and remove or disable the extension

## Advanced Configuration

### Custom Server URL

```python
from stagehand import Stagehand

async with Stagehand(
    env="EXTENSION",
    # Extension server URL is hardcoded in browser.py
    # To change, modify connect_extension_browser() in stagehand/browser.py
) as stagehand:
    ...
```

### Using Different Tab

By default, the extension attaches to the **active tab**. To control a specific tab, you'll need to modify the extension's `GET_ACTIVE_TAB` logic in `background.js`.

### Multiple Python Clients

The server supports multiple Python clients connecting simultaneously. Each gets its own session and can control different tabs (or the same tab if configured).

## Security Considerations

- The WebSocket server runs on `localhost:8766` (only accessible from your machine)
- The extension requires `debugger` permission (shows warning in Chrome)
- CDP access gives full control over the browser (can read/write all page content)
- For enterprise: Deploy via Chrome Policy to pre-approve permissions

## Next Steps

- See `examples/` folder for more usage examples
- Read main README.md for Stagehand features
- Check server logs for debugging: `python server/extension_server.py`

## Getting Help

If you encounter issues:

1. Check the server logs for errors
2. Open Chrome DevTools console (F12) on any page and look for Stagehand errors
3. Check the extension's background script logs: `chrome://extensions/` → "Stagehand Extension Bridge" → "Inspect views: background page"
4. File an issue at https://github.com/browserbase/stagehand-python/issues
