# Stagehand Extension Server

WebSocket server that bridges Stagehand Python and Chrome Extension.

## Installation

```bash
pip install -r requirements.txt
```

## Running

```bash
python extension_server.py
```

The server will start on `ws://localhost:8766` and wait for:
1. Chrome Extension to connect
2. Python clients to connect

## Architecture

```
Python Client → WebSocket → Server → WebSocket → Chrome Extension
                (port 8766)                         (port 8766)
```

The server:
- Routes messages bidirectionally
- Maintains session state
- Handles request/response matching
- Forwards CDP events
- Manages timeouts

## Logs

The server logs all connections, disconnections, and errors to stdout.
