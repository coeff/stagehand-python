# Stagehand Chrome Extension

This extension bridges Stagehand Python with Chrome's DevTools Protocol (CDP) for AI-powered browser automation.

## Files

- **manifest.json** - Extension configuration
- **background.js** - Service worker that handles CDP communication
- **content.js** - Injected script (domScripts.js) that runs on every page
- **popup.html/js** - UI to show connection status
- **icon*.png** - Extension icons (16x16, 48x48, 128x128)

## How It Works

1. Background script connects to Python WebSocket server (`localhost:8766`)
2. Python sends commands (CDP, evaluate, navigate, etc.)
3. Extension forwards to Chrome DevTools Protocol
4. Results are sent back to Python

## Icons

To generate icons, you can use any image editor or online tool. For testing, you can use placeholder icons.
