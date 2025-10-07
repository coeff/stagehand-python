# Quick Start: Extension Mode

Follow these steps to run Stagehand in extension mode:

## 1. Install Server Dependencies

```bash
pip install websockets
```

## 2. Start the Server

Open Terminal 1:

```bash
cd server
python extension_server.py
```

Leave this running. You should see:

```
✅ Server running on ws://localhost:8766
```

## 3. Load Chrome Extension

1. Open Chrome
2. Go to `chrome://extensions/`
3. Toggle "Developer mode" ON (top-right)
4. Click "Load unpacked"
5. Select the `chrome_extension` folder
6. The extension "Stagehand Extension Bridge" should now appear

## 4. Verify Connection

- Click the Stagehand extension icon in Chrome toolbar
- It should show: "✅ Connected to Python server"

## 5. Run Example

Open Terminal 2:

```bash
# Make sure you're in the repo root
python examples/extension_example.py
```

This will:
- Connect to your Chrome browser
- Navigate to ycombinator.com in your active tab
- Extract company data using AI
- Find and click on Browserbase link

## Troubleshooting

**Extension not connecting?**
- Make sure server is running (Terminal 1)
- Refresh the extension: go to `chrome://extensions/` and click reload icon

**"No active tab"?**
- Open a new Chrome tab before running the Python script

**"Debugger already attached"?**
- Close Chrome DevTools (F12) if open
- Close other automation tools

## What's Happening?

```
Python Script → WebSocket → Server → WebSocket → Extension → CDP → Your Chrome Tab
```

The extension uses Chrome's debugging protocol (CDP) to control your browser, just like Playwright or Puppeteer, but works with your existing Chrome instance!

## Next Steps

- Read full setup in `EXTENSION_SETUP.md`
- Try more examples in `examples/` folder
- Customize for your use case

## Stopping

1. Press Ctrl+C in Python script terminal (Terminal 2)
2. Press Ctrl+C in server terminal (Terminal 1)
3. (Optional) Unload extension from `chrome://extensions/`
