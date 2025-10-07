#!/usr/bin/env python3
"""
Stagehand Extension WebSocket Server

This server bridges between Stagehand Python and the Chrome Extension.
It routes messages bidirectionally and maintains session state.
"""

import asyncio
import json
import logging
import uuid
from typing import Dict, Optional, Set
from dataclasses import dataclass, field
import websockets
from websockets.server import WebSocketServerProtocol

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


@dataclass
class PendingRequest:
    """Represents a pending request waiting for response"""
    future: asyncio.Future
    timeout_handle: Optional[asyncio.TimerHandle] = None


@dataclass
class Session:
    """Represents a Stagehand Python client session"""
    session_id: str
    websocket: WebSocketServerProtocol
    tab_id: Optional[int] = None
    pending_requests: Dict[str, PendingRequest] = field(default_factory=dict)


class ExtensionServer:
    """WebSocket server that bridges Stagehand Python and Chrome Extension"""

    def __init__(self, host='localhost', python_port=8766, extension_port=8766):
        self.host = host
        self.python_port = python_port
        self.extension_ws: Optional[WebSocketServerProtocol] = None
        self.sessions: Dict[str, Session] = {}
        self.request_timeout = 30  # seconds

    async def handle_extension(self, websocket: WebSocketServerProtocol):
        """Handle connection from Chrome extension"""
        logger.info("Chrome extension connected")
        self.extension_ws = websocket

        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                    await self.handle_extension_message(data)
                except json.JSONDecodeError as e:
                    logger.error(f"Invalid JSON from extension: {e}")
                except Exception as e:
                    logger.error(f"Error handling extension message: {e}", exc_info=True)
        except websockets.exceptions.ConnectionClosed:
            logger.info("Chrome extension disconnected")
        finally:
            self.extension_ws = None
            # Notify all Python clients
            for session in list(self.sessions.values()):
                try:
                    await session.websocket.send(json.dumps({
                        'type': 'EXTENSION_DISCONNECTED',
                        'error': 'Chrome extension disconnected'
                    }))
                except:
                    pass

    async def handle_extension_message(self, data: dict):
        """Handle messages from Chrome extension"""
        msg_type = data.get('type')

        if msg_type == 'EXTENSION_READY':
            logger.info("Extension ready")
            return

        if msg_type == 'PING':
            # Respond to keepalive
            if self.extension_ws:
                await self.extension_ws.send(json.dumps({'type': 'PONG'}))
            return

        if msg_type == 'RESPONSE':
            # Route response back to Python client
            request_id = data.get('id')
            if request_id:
                await self.route_response_to_python(request_id, data)
            return

        if msg_type == 'CDP_EVENT':
            # Forward CDP event to all interested Python clients
            await self.forward_cdp_event(data)
            return

        if msg_type in ['DEBUGGER_DETACHED', 'TAB_CLOSED']:
            # Notify Python clients
            await self.notify_python_clients(data)
            return

    async def route_response_to_python(self, request_id: str, response: dict):
        """Route response from extension back to Python client"""
        # Find session with this pending request
        for session in self.sessions.values():
            if request_id in session.pending_requests:
                pending = session.pending_requests.pop(request_id)

                # Cancel timeout
                if pending.timeout_handle:
                    pending.timeout_handle.cancel()

                # Set result
                if response.get('success'):
                    pending.future.set_result(response.get('result'))
                else:
                    error_msg = response.get('error', 'Unknown error')
                    pending.future.set_exception(Exception(error_msg))
                return

        logger.warning(f"No pending request found for ID: {request_id}")

    async def forward_cdp_event(self, event: dict):
        """Forward CDP event to relevant Python sessions"""
        tab_id = event.get('tabId')

        for session in self.sessions.values():
            if session.tab_id == tab_id or session.tab_id is None:
                try:
                    await session.websocket.send(json.dumps(event))
                except Exception as e:
                    logger.error(f"Error forwarding CDP event to session {session.session_id}: {e}")

    async def notify_python_clients(self, notification: dict):
        """Send notification to all Python clients"""
        for session in self.sessions.values():
            try:
                await session.websocket.send(json.dumps(notification))
            except Exception as e:
                logger.error(f"Error notifying session {session.session_id}: {e}")

    async def handle_python_client(self, websocket: WebSocketServerProtocol):
        """Handle connection from Stagehand Python client"""
        session_id = str(uuid.uuid4())
        session = Session(session_id=session_id, websocket=websocket)
        self.sessions[session_id] = session

        logger.info(f"Python client connected: {session_id}")

        try:
            # Send welcome message
            await websocket.send(json.dumps({
                'type': 'CONNECTED',
                'session_id': session_id,
                'extension_connected': self.extension_ws is not None
            }))

            async for message in websocket:
                try:
                    data = json.loads(message)
                    await self.handle_python_message(session, data)
                except json.JSONDecodeError as e:
                    logger.error(f"Invalid JSON from Python client: {e}")
                    await websocket.send(json.dumps({
                        'type': 'ERROR',
                        'error': 'Invalid JSON'
                    }))
                except Exception as e:
                    logger.error(f"Error handling Python message: {e}", exc_info=True)
                    await websocket.send(json.dumps({
                        'type': 'ERROR',
                        'error': str(e)
                    }))
        except websockets.exceptions.ConnectionClosed:
            logger.info(f"Python client disconnected: {session_id}")
        finally:
            # Clean up session
            for pending in session.pending_requests.values():
                if pending.timeout_handle:
                    pending.timeout_handle.cancel()
                if not pending.future.done():
                    pending.future.set_exception(Exception("Session closed"))
            del self.sessions[session_id]

    async def handle_python_message(self, session: Session, data: dict):
        """Handle messages from Python client"""
        msg_type = data.get('type')
        request_id = data.get('id')

        # Check if extension is connected
        if not self.extension_ws:
            await session.websocket.send(json.dumps({
                'id': request_id,
                'type': 'ERROR',
                'error': 'Chrome extension not connected'
            }))
            return

        # Store tab ID if provided
        if 'tabId' in data and session.tab_id is None:
            session.tab_id = data['tabId']

        # Forward to extension and wait for response
        if request_id:
            await self.forward_with_response(session, request_id, data)
        else:
            # Fire and forget
            await self.extension_ws.send(json.dumps(data))

    async def forward_with_response(self, session: Session, request_id: str, data: dict):
        """Forward request to extension and wait for response"""
        # Create future for response
        future = asyncio.Future()

        # Set timeout
        loop = asyncio.get_event_loop()
        timeout_handle = loop.call_later(
            self.request_timeout,
            self.handle_request_timeout,
            session,
            request_id
        )

        # Store pending request
        session.pending_requests[request_id] = PendingRequest(
            future=future,
            timeout_handle=timeout_handle
        )

        try:
            # Forward to extension
            await self.extension_ws.send(json.dumps(data))

            # Wait for response
            result = await future

            # Send result back to Python client
            await session.websocket.send(json.dumps({
                'id': request_id,
                'type': 'RESPONSE',
                'result': result,
                'success': True
            }))

        except Exception as e:
            logger.error(f"Error forwarding request {request_id}: {e}")

            # Send error back to Python client
            await session.websocket.send(json.dumps({
                'id': request_id,
                'type': 'RESPONSE',
                'error': str(e),
                'success': False
            }))

    def handle_request_timeout(self, session: Session, request_id: str):
        """Handle request timeout"""
        if request_id in session.pending_requests:
            pending = session.pending_requests.pop(request_id)
            if not pending.future.done():
                pending.future.set_exception(TimeoutError(f"Request {request_id} timed out after {self.request_timeout}s"))

    async def start(self):
        """Start the WebSocket server"""
        logger.info(f"Starting Stagehand Extension Server...")
        logger.info(f"Extension will connect to: ws://{self.host}:{self.python_port}")
        logger.info(f"Python clients connect to: ws://{self.host}:{self.python_port}")

        # For simplicity, use same port for both (extension detects itself)
        async def handler(websocket, path):
            # Determine if this is extension or Python client based on first message
            try:
                first_message = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                data = json.loads(first_message)

                # Extension sends EXTENSION_READY on connect
                if data.get('type') == 'EXTENSION_READY':
                    # Put message back for processing
                    await self.handle_extension(websocket)
                else:
                    # This is a Python client
                    # Create async generator to replay first message
                    async def message_gen():
                        yield first_message
                        async for msg in websocket:
                            yield msg

                    # Handle as Python client
                    session_id = str(uuid.uuid4())
                    session = Session(session_id=session_id, websocket=websocket)
                    self.sessions[session_id] = session

                    logger.info(f"Python client connected: {session_id}")

                    try:
                        # Send welcome message
                        await websocket.send(json.dumps({
                            'type': 'CONNECTED',
                            'session_id': session_id,
                            'extension_connected': self.extension_ws is not None
                        }))

                        # Process first message
                        await self.handle_python_message(session, data)

                        # Process remaining messages
                        async for message in websocket:
                            try:
                                msg_data = json.loads(message)
                                await self.handle_python_message(session, msg_data)
                            except Exception as e:
                                logger.error(f"Error: {e}", exc_info=True)
                    finally:
                        del self.sessions[session_id]

            except asyncio.TimeoutError:
                logger.error("Client didn't send initial message in time")
            except Exception as e:
                logger.error(f"Error in handler: {e}", exc_info=True)

        async with websockets.serve(handler, self.host, self.python_port):
            logger.info(f"✅ Server running on ws://{self.host}:{self.python_port}")
            await asyncio.Future()  # Run forever


async def main():
    """Main entry point"""
    server = ExtensionServer()
    await server.start()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
