import asyncio
import json
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any, Optional

from browserbase import Browserbase
from browserbase.types import SessionCreateParams as BrowserbaseSessionCreateParams
from playwright.async_api import (
    Browser,
    BrowserContext,
    Playwright,
)

try:
    import websockets
except ImportError:
    websockets = None

from .context import StagehandContext
from .logging import StagehandLogger
from .page import StagehandPage


async def connect_browserbase_browser(
    playwright: Playwright,
    session_id: str,
    browserbase_api_key: str,
    stagehand_instance: Any,
    logger: StagehandLogger,
) -> tuple[Browser, BrowserContext, StagehandContext, StagehandPage]:
    """
    Connect to a Browserbase remote browser session.

    Args:
        playwright: The Playwright instance
        session_id: The Browserbase session ID
        browserbase_api_key: The Browserbase API key
        stagehand_instance: The Stagehand instance (for context initialization)
        logger: The logger instance

    Returns:
        tuple of (browser, context, stagehand_context, page)
    """
    # Connect to remote browser via Browserbase SDK and CDP
    bb = Browserbase(api_key=browserbase_api_key)
    try:
        if session_id:
            session = bb.sessions.retrieve(session_id)
            if session.status != "RUNNING":
                raise RuntimeError(
                    f"Browserbase session {session_id} is not running (status: {session.status})"
                )
        else:
            browserbase_session_create_params = (
                BrowserbaseSessionCreateParams(
                    project_id=stagehand_instance.browserbase_project_id,
                    browser_settings={
                        "viewport": {
                            "width": 1024,
                            "height": 768,
                        },
                    },
                )
                if not stagehand_instance.browserbase_session_create_params
                else stagehand_instance.browserbase_session_create_params
            )
            session = bb.sessions.create(**browserbase_session_create_params)
            if not session.id:
                raise Exception("Could not create Browserbase session")
            stagehand_instance.session_id = session.id
        connect_url = session.connectUrl
    except Exception as e:
        logger.error(f"Error retrieving or validating Browserbase session: {str(e)}")
        raise

    logger.debug(f"Connecting to remote browser at: {connect_url}")
    try:
        browser = await playwright.chromium.connect_over_cdp(connect_url)
    except Exception as e:
        logger.error(f"Failed to connect Playwright via CDP: {str(e)}")
        raise

    existing_contexts = browser.contexts
    logger.debug(f"Existing contexts in remote browser: {len(existing_contexts)}")
    if existing_contexts:
        context = existing_contexts[0]
    else:
        # This case might be less common with Browserbase but handle it
        logger.warning(
            "No existing context found in remote browser, creating a new one."
        )
        context = await browser.new_context()

    stagehand_context = await StagehandContext.init(context, stagehand_instance)

    # Access or create a page via StagehandContext
    existing_pages = context.pages
    logger.debug(f"Existing pages in context: {len(existing_pages)}")
    if existing_pages:
        logger.debug("Using existing page via StagehandContext")
        page = await stagehand_context.get_stagehand_page(existing_pages[0])
    else:
        logger.debug("Creating a new page via StagehandContext")
        page = await stagehand_context.new_page()

    return browser, context, stagehand_context, page


async def connect_local_browser(
    playwright: Playwright,
    local_browser_launch_options: dict[str, Any],
    stagehand_instance: Any,
    logger: StagehandLogger,
) -> tuple[
    Optional[Browser], BrowserContext, StagehandContext, StagehandPage, Optional[Path]
]:
    """
    Connect to a local browser via CDP or launch a new browser context.

    Args:
        playwright: The Playwright instance
        local_browser_launch_options: Options for launching the local browser
        stagehand_instance: The Stagehand instance (for context initialization)
        logger: The logger instance

    Returns:
        tuple of (browser, context, stagehand_context, page, temp_user_data_dir)
    """
    cdp_url = local_browser_launch_options.get("cdp_url")
    temp_user_data_dir = None

    if cdp_url:
        logger.info(f"Connecting to local browser via CDP URL: {cdp_url}")
        try:
            browser = await playwright.chromium.connect_over_cdp(
                cdp_url, headers=local_browser_launch_options.get("headers")
            )

            if not browser.contexts:
                raise RuntimeError(f"No browser contexts found at CDP URL: {cdp_url}")
            context = browser.contexts[0]
            stagehand_context = await StagehandContext.init(context, stagehand_instance)
            logger.debug(f"Connected via CDP. Using context: {context}")
        except Exception as e:
            logger.error(f"Failed to connect via CDP URL ({cdp_url}): {str(e)}")
            raise
    else:
        logger.info("Launching new local browser context...")
        browser = None

        user_data_dir_option = local_browser_launch_options.get("user_data_dir")
        if user_data_dir_option:
            user_data_dir = Path(user_data_dir_option).resolve()
        else:
            # Create temporary directory
            temp_dir = tempfile.mkdtemp(prefix="stagehand_ctx_")
            temp_user_data_dir = Path(temp_dir)
            user_data_dir = temp_user_data_dir
            # Create Default profile directory and Preferences file like in TS
            default_profile_path = user_data_dir / "Default"
            default_profile_path.mkdir(parents=True, exist_ok=True)
            prefs_path = default_profile_path / "Preferences"
            default_prefs = {"plugins": {"always_open_pdf_externally": True}}
            try:
                with open(prefs_path, "w") as f:
                    json.dump(default_prefs, f)
                logger.debug(
                    f"Created temporary user_data_dir with default preferences: {user_data_dir}"
                )
            except Exception as e:
                logger.error(
                    f"Failed to write default preferences to {prefs_path}: {e}"
                )

        downloads_path_option = local_browser_launch_options.get("downloads_path")
        if downloads_path_option:
            downloads_path = str(Path(downloads_path_option).resolve())
        else:
            downloads_path = str(Path.cwd() / "downloads")
        try:
            os.makedirs(downloads_path, exist_ok=True)
            logger.debug(f"Using downloads_path: {downloads_path}")
        except Exception as e:
            logger.error(f"Failed to create downloads_path {downloads_path}: {e}")

        # Prepare Launch Options (translate keys if needed)
        launch_options = {
            "headless": local_browser_launch_options.get("headless", False),
            "accept_downloads": local_browser_launch_options.get(
                "acceptDownloads", True
            ),
            "downloads_path": downloads_path,
            "args": local_browser_launch_options.get(
                "args",
                [
                    "--disable-blink-features=AutomationControlled",
                ],
            ),
            "viewport": local_browser_launch_options.get(
                "viewport", {"width": 1024, "height": 768}
            ),
            "locale": local_browser_launch_options.get("locale", "en-US"),
            "timezone_id": local_browser_launch_options.get(
                "timezoneId", "America/New_York"
            ),
            "bypass_csp": local_browser_launch_options.get("bypassCSP", True),
            "proxy": local_browser_launch_options.get("proxy"),
            "ignore_https_errors": local_browser_launch_options.get(
                "ignoreHTTPSErrors", True
            ),
        }
        launch_options = {k: v for k, v in launch_options.items() if v is not None}

        # Launch Context
        try:
            context = await playwright.chromium.launch_persistent_context(
                str(user_data_dir),  # Needs to be string path
                **launch_options,
            )
            stagehand_context = await StagehandContext.init(context, stagehand_instance)
            logger.info("Local browser context launched successfully.")
            browser = context.browser

        except Exception as e:
            logger.error(f"Failed to launch local browser context: {str(e)}")
            if temp_user_data_dir:
                try:
                    shutil.rmtree(temp_user_data_dir)
                except Exception:
                    pass
            raise

        cookies = local_browser_launch_options.get("cookies")
        if cookies:
            try:
                await context.add_cookies(cookies)
                logger.debug(f"Added {len(cookies)} cookies to the context.")
            except Exception as e:
                logger.error(f"Failed to add cookies: {e}")

    # Apply stealth scripts
    await apply_stealth_scripts(context, logger)

    # Get the initial page (usually one is created by default)
    if context.pages:
        playwright_page = context.pages[0]
        logger.debug("Using initial page from local context.")
        page = await stagehand_context.get_stagehand_page(playwright_page)
    else:
        logger.debug("No initial page found, creating a new one.")
        page = await stagehand_context.new_page()

    return browser, context, stagehand_context, page, temp_user_data_dir


async def apply_stealth_scripts(context: BrowserContext, logger: StagehandLogger):
    """Applies JavaScript init scripts to make the browser less detectable."""
    logger.debug("Applying stealth scripts to the context...")
    stealth_script = """
    (() => {
        // Override navigator.webdriver
        if (navigator.webdriver) {
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        }

        // Mock languages and plugins
        Object.defineProperty(navigator, 'languages', {
            get: () => ['en-US', 'en'],
        });

        // Avoid complex plugin mocking, just return a non-empty array like structure
        if (navigator.plugins instanceof PluginArray && navigator.plugins.length === 0) {
             Object.defineProperty(navigator, 'plugins', {
                get: () => Object.values({
                    'plugin1': { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
                    'plugin2': { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '' },
                    'plugin3': { name: 'Native Client', filename: 'internal-nacl-plugin', description: '' }
                }),
            });
        }

        // Remove Playwright-specific properties from window
        try {
            delete window.__playwright_run; // Example property, check actual properties if needed
            delete window.navigator.__proto__.webdriver; // Another common place
        } catch (e) {}

        // Override permissions API (example for notifications)
        if (window.navigator && window.navigator.permissions) {
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => {
                if (parameters && parameters.name === 'notifications') {
                    return Promise.resolve({ state: Notification.permission });
                }
                // Call original for other permissions
                return originalQuery.apply(window.navigator.permissions, [parameters]);
            };
        }
    })();
    """
    try:
        await context.add_init_script(stealth_script)
    except Exception as e:
        logger.error(f"Failed to add stealth init script: {str(e)}")


async def cleanup_browser_resources(
    browser: Optional[Browser],
    context: Optional[BrowserContext],
    playwright: Optional[Playwright],
    temp_user_data_dir: Optional[Path],
    logger: StagehandLogger,
):
    """
    Clean up browser resources.

    Args:
        browser: The browser instance (if any)
        context: The browser context
        playwright: The Playwright instance
        temp_user_data_dir: Temporary user data directory to remove (if any)
        logger: The logger instance
    """
    if context:
        try:
            logger.debug("Closing browser context...")
            await context.close()
        except Exception as e:
            logger.error(f"Error closing context: {str(e)}")
    if browser:
        try:
            logger.debug("Closing browser...")
            await browser.close()
        except Exception as e:
            logger.error(f"Error closing browser: {str(e)}")

    # Clean up temporary user data directory if created
    if temp_user_data_dir:
        try:
            logger.debug(
                f"Removing temporary user data directory: {temp_user_data_dir}"
            )
            shutil.rmtree(temp_user_data_dir)
        except Exception as e:
            logger.error(
                f"Error removing temporary directory {temp_user_data_dir}: {str(e)}"
            )

    if playwright:
        try:
            logger.debug("Stopping Playwright...")
            await playwright.stop()
        except Exception as e:
            logger.error(f"Error stopping Playwright: {str(e)}")


# ============================================================================
# Extension Mode - Connection to Chrome Extension via WebSocket
# ============================================================================


async def connect_extension_browser(
    stagehand_instance: Any,
    logger: StagehandLogger,
    server_url: str = "ws://localhost:8766",
) -> tuple[None, "ExtensionContext", StagehandContext, StagehandPage]:
    """
    Connect to Chrome extension via WebSocket server.

    Args:
        stagehand_instance: The Stagehand instance
        logger: The logger instance
        server_url: WebSocket server URL (default: ws://localhost:8766)

    Returns:
        tuple of (None, extension_context, stagehand_context, page)
    """
    if websockets is None:
        raise ImportError(
            "websockets package is required for EXTENSION mode. "
            "Install it with: pip install websockets"
        )

    logger.info(f"Connecting to extension server at {server_url}")

    try:
        # Connect to WebSocket server
        ws = await websockets.connect(server_url)
        logger.info("Connected to extension server")

        # Send initial message (server needs this to identify us as Python client)
        await ws.send(json.dumps({'type': 'INIT'}))

        # Wait for welcome message (before starting manager)
        welcome = await asyncio.wait_for(ws.recv(), timeout=5.0)
        welcome_data = json.loads(welcome)

        if welcome_data.get('type') != 'CONNECTED':
            raise RuntimeError(f"Unexpected welcome message: {welcome_data}")

        if not welcome_data.get('extension_connected'):
            logger.warning("Chrome extension is not connected to server!")
            logger.warning("Make sure the extension is loaded in Chrome")

        session_id = welcome_data['session_id']
        logger.info(f"Session ID: {session_id}")

        # NOW start the WebSocket manager (after initial handshake)
        ws_manager = WebSocketManager(ws)
        await ws_manager.start()

        # Get active tab from extension
        tab_info = await send_extension_command(
            ws_manager, 'GET_ACTIVE_TAB', {}, timeout=5.0
        )

        tab_id = tab_info['tabId']
        logger.info(f"Active tab: {tab_id} - {tab_info.get('title', 'Untitled')}")

        # Attach debugger to tab
        try:
            await send_extension_command(
                ws_manager, 'ATTACH_DEBUGGER', {'tabId': tab_id}, timeout=5.0
            )
            logger.info(f"Debugger attached to tab {tab_id}")
        except RuntimeError as e:
            if "Cannot access a chrome://" in str(e):
                logger.error("Cannot attach debugger to chrome:// pages")
                logger.error("Please open a regular website (like google.com) as your active tab and try again")
            raise

        # Create extension context
        extension_context = ExtensionContext(ws_manager, tab_id, logger, stagehand_instance)

        # Create Stagehand context
        stagehand_context = await StagehandContext.init(extension_context, stagehand_instance)

        # Get or create page
        page = await stagehand_context.new_page()

        logger.info("Extension browser connection established")
        return None, extension_context, stagehand_context, page

    except Exception as e:
        logger.error(f"Failed to connect to extension: {e}")
        raise


class WebSocketManager:
    """Manages WebSocket communication with message routing"""

    def __init__(self, ws: websockets.WebSocketClientProtocol):
        self.ws = ws
        self.pending_responses = {}  # request_id -> Future
        self.event_handlers = {}  # event_name -> list of callbacks
        self._receiver_task = None

    async def start(self):
        """Start the message receiver task"""
        self._receiver_task = asyncio.create_task(self._message_receiver())

    async def _message_receiver(self):
        """Background task that receives and routes all messages"""
        try:
            async for message in self.ws:
                try:
                    data = json.loads(message)

                    # Route response messages
                    if data.get('type') == 'RESPONSE' and data.get('id') in self.pending_responses:
                        future = self.pending_responses.pop(data['id'])
                        if not future.done():
                            if data.get('success'):
                                future.set_result(data.get('result'))
                            else:
                                future.set_exception(RuntimeError(data.get('error', 'Unknown error')))

                    # Route CDP events
                    elif data.get('type') == 'CDP_EVENT':
                        event_name = data.get('method')
                        if event_name in self.event_handlers:
                            params = data.get('params', {})
                            for callback in self.event_handlers[event_name]:
                                try:
                                    callback(params)
                                except Exception as e:
                                    print(f"Error in event handler: {e}")

                except json.JSONDecodeError:
                    pass
                except Exception as e:
                    print(f"Error processing message: {e}")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"Error in message receiver: {e}")

    async def send_command(self, command_type: str, params: dict, timeout: float = 30.0) -> Any:
        """Send command and wait for response"""
        request_id = str(uuid.uuid4())

        message = {
            'id': request_id,
            'type': command_type,
            **params
        }

        # Create future for response
        future = asyncio.Future()
        self.pending_responses[request_id] = future

        # Send message
        await self.ws.send(json.dumps(message))

        # Wait for response with timeout
        try:
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            self.pending_responses.pop(request_id, None)
            raise TimeoutError(f"Command {command_type} timed out after {timeout}s")

    def register_event_handler(self, event_name: str, callback):
        """Register an event handler"""
        if event_name not in self.event_handlers:
            self.event_handlers[event_name] = []
        self.event_handlers[event_name].append(callback)

    def unregister_event_handler(self, event_name: str, callback):
        """Unregister an event handler"""
        if event_name in self.event_handlers:
            try:
                self.event_handlers[event_name].remove(callback)
            except ValueError:
                pass

    async def close(self):
        """Close the WebSocket manager"""
        if self._receiver_task:
            self._receiver_task.cancel()
            try:
                await self._receiver_task
            except asyncio.CancelledError:
                pass


async def send_extension_command(
    ws_or_manager,
    command_type: str,
    params: dict,
    timeout: float = 30.0
) -> Any:
    """Send command to extension and wait for response"""
    # Support both WebSocketManager and raw WebSocket (for backwards compat)
    if isinstance(ws_or_manager, WebSocketManager):
        return await ws_or_manager.send_command(command_type, params, timeout)

    # Fallback for raw WebSocket (deprecated, will cause issues with concurrent recv)
    ws = ws_or_manager
    request_id = str(uuid.uuid4())

    message = {
        'id': request_id,
        'type': command_type,
        **params
    }

    await ws.send(json.dumps(message))

    # Wait for response
    start_time = asyncio.get_event_loop().time()
    while True:
        if asyncio.get_event_loop().time() - start_time > timeout:
            raise TimeoutError(f"Command {command_type} timed out after {timeout}s")

        try:
            response = await asyncio.wait_for(ws.recv(), timeout=1.0)
            response_data = json.loads(response)

            # Check if this is our response
            if response_data.get('id') == request_id and response_data.get('type') == 'RESPONSE':
                if response_data.get('success'):
                    return response_data.get('result')
                else:
                    error = response_data.get('error', 'Unknown error')
                    raise RuntimeError(f"Extension command failed: {error}")

        except asyncio.TimeoutError:
            # Continue waiting
            continue


class ExtensionContext:
    """Mimics Playwright BrowserContext for extension mode"""

    def __init__(self, ws_manager: WebSocketManager, tab_id: int, logger: StagehandLogger, stagehand: Any):
        self.ws_manager = ws_manager
        self.tab_id = tab_id
        self.logger = logger
        self.stagehand = stagehand
        self._pages = []
        self._cdp_sessions = {}

    async def new_cdp_session(self, page: "StagehandPage") -> "ExtensionCDPSession":
        """Create a new CDP session (returns wrapper around WebSocket)"""
        session = ExtensionCDPSession(self.ws_manager, self.tab_id, self.logger)
        self._cdp_sessions[id(page)] = session
        return session

    @property
    def pages(self) -> list:
        """Return list of pages (just the current tab)"""
        return self._pages

    async def new_page(self):
        """Create/return a page wrapper for the current tab"""
        # In extension mode, we work with the existing tab
        # Create a mock page object that wraps the tab
        page = ExtensionPage(self.ws_manager, self.tab_id, self.logger, context=self)
        self._pages.append(page)
        return page

    async def add_cookies(self, cookies: list):
        """Add cookies via extension"""
        result = await send_extension_command(
            self.ws_manager,
            'SET_COOKIES',
            {'cookies': cookies}
        )
        return result

    def on(self, event: str, handler):
        """Register event handler (no-op for extension, events handled differently)"""
        # Extension context doesn't have page-level events like Playwright
        # These are typically handled at the CDP session level
        pass

    async def close(self):
        """Close the context (detach debugger)"""
        try:
            await send_extension_command(
                self.ws_manager,
                'DETACH_DEBUGGER',
                {'tabId': self.tab_id},
                timeout=5.0
            )
        except Exception as e:
            self.logger.error(f"Error detaching debugger: {e}")

        try:
            await self.ws_manager.close()
        except Exception as e:
            self.logger.error(f"Error closing WebSocket manager: {e}")


class ExtensionCDPSession:
    """Mimics Playwright CDPSession for extension mode"""

    def __init__(self, ws_manager: WebSocketManager, tab_id: int, logger: StagehandLogger):
        self.ws_manager = ws_manager
        self.tab_id = tab_id
        self.logger = logger
        self._listeners = {}  # eventName -> list of callbacks
        self._listener_ids = {}  # eventName -> listener ID

    async def send(self, method: str, params: Optional[dict] = None) -> dict:
        """Send CDP command via extension"""
        result = await send_extension_command(
            self.ws_manager,
            'CDP_COMMAND',
            {
                'method': method,
                'params': params or {},
                'tabId': self.tab_id
            }
        )
        return result or {}

    def on(self, event_name: str, callback):
        """Register event listener"""
        if event_name not in self._listeners:
            self._listeners[event_name] = []
            # Register with server
            listener_id = str(uuid.uuid4())
            self._listener_ids[event_name] = listener_id

            # Register with WebSocket manager
            self.ws_manager.register_event_handler(event_name, callback)

            # Send registration command (fire and forget)
            asyncio.create_task(send_extension_command(
                self.ws_manager,
                'REGISTER_CDP_LISTENER',
                {
                    'tabId': self.tab_id,
                    'eventName': event_name,
                    'listenerId': listener_id
                },
                timeout=5.0
            ))

        self._listeners[event_name].append(callback)

    def remove_listener(self, event_name: str, callback):
        """Remove event listener"""
        if event_name in self._listeners:
            try:
                self._listeners[event_name].remove(callback)

                # If no more listeners, unregister with server
                if not self._listeners[event_name]:
                    del self._listeners[event_name]
                    if event_name in self._listener_ids:
                        listener_id = self._listener_ids.pop(event_name)
                        asyncio.create_task(send_extension_command(
                            self.ws_manager,
                            'UNREGISTER_CDP_LISTENER',
                            {
                                'tabId': self.tab_id,
                                'eventName': event_name,
                                'listenerId': listener_id
                            },
                            timeout=5.0
                        ))
            except ValueError:
                pass

    def is_connected(self) -> bool:
        """Check if session is connected"""
        return self.ws_manager.ws.open

    async def detach(self):
        """Detach CDP session (no-op, cleanup handled by manager)"""
        pass


class ExtensionPage:
    """Mimics Playwright Page for extension mode"""

    def __init__(self, ws_manager: WebSocketManager, tab_id: int, logger: StagehandLogger, context=None):
        self.ws_manager = ws_manager
        self.tab_id = tab_id
        self.logger = logger
        self._url = None
        self._context = context

    async def goto(self, url: str, **options):
        """Navigate to URL"""
        result = await send_extension_command(
            self.ws_manager,
            'NAVIGATE',
            {
                'tabId': self.tab_id,
                'url': url,
                'options': options
            }
        )
        self._url = url
        return result

    async def url(self) -> str:
        """Get current URL"""
        if self._url:
            return self._url
        # Get from tab info
        tab_info = await send_extension_command(
            self.ws_manager,
            'GET_TAB_INFO',
            {'tabId': self.tab_id}
        )
        return tab_info.get('url', '')

    async def title(self) -> str:
        """Get page title"""
        tab_info = await send_extension_command(
            self.ws_manager,
            'GET_TAB_INFO',
            {'tabId': self.tab_id}
        )
        return tab_info.get('title', '')

    async def evaluate(self, script: str, *args):
        """Evaluate JavaScript"""
        result = await send_extension_command(
            self.ws_manager,
            'EVALUATE',
            {
                'tabId': self.tab_id,
                'script': script,
                'args': list(args)
            }
        )
        return result

    async def wait_for_load_state(self, state: str = "load", **options):
        """Wait for load state (no-op for now, could implement with navigation listener)"""
        # For extension mode, we rely on navigation completion from the extension
        await asyncio.sleep(0.5)  # Small delay to ensure page is ready

    async def add_init_script(self, script: str):
        """Add initialization script (injected via content script in extension mode)"""
        # In extension mode, domScripts are already injected via content.js automatically
        # This is a no-op since content scripts are loaded from manifest.json
        # All necessary scripts are already present on every page
        pass

    def on(self, event: str, handler):
        """Register event handler (no-op for extension page)"""
        # Extension page doesn't support event handlers
        pass

    def once(self, event: str, handler):
        """Register one-time event handler (no-op for extension page)"""
        # Extension page doesn't support event handlers
        pass

    @property
    def context(self):
        """Get the context"""
        return self._context

    def locator(self, selector: str):
        """Get a locator for the given selector"""
        return ExtensionLocator(self.ws_manager, self.tab_id, selector, self.logger)

    async def close(self):
        """Close the page"""
        await send_extension_command(
            self.ws_manager,
            'CLOSE_TAB',
            {'tabId': self.tab_id}
        )


class ExtensionLocator:
    """Mimics Playwright Locator for extension mode"""

    def __init__(self, ws_manager: WebSocketManager, tab_id: int, selector: str, logger: StagehandLogger):
        self.ws_manager = ws_manager
        self.tab_id = tab_id
        self.selector = selector
        self.logger = logger

    async def click(self, **options):
        """Click the element"""
        script = f"""
        (function() {{
            const element = document.evaluate(
                '{self.selector.replace("xpath=", "")}',
                document,
                null,
                XPathResult.FIRST_ORDERED_NODE_TYPE,
                null
            ).singleNodeValue;
            if (element) {{
                element.click();
                return true;
            }}
            return false;
        }})()
        """
        result = await send_extension_command(
            self.ws_manager,
            'EVALUATE',
            {
                'tabId': self.tab_id,
                'script': script,
                'args': []
            }
        )
        return result

    async def fill(self, value: str, **options):
        """Fill the element with text"""
        script = f"""
        (function() {{
            const element = document.evaluate(
                '{self.selector.replace("xpath=", "")}',
                document,
                null,
                XPathResult.FIRST_ORDERED_NODE_TYPE,
                null
            ).singleNodeValue;
            if (element) {{
                element.value = '{value}';
                element.dispatchEvent(new Event('input', {{ bubbles: true }}));
                element.dispatchEvent(new Event('change', {{ bubbles: true }}));
                return true;
            }}
            return false;
        }})()
        """
        result = await send_extension_command(
            self.ws_manager,
            'EVALUATE',
            {
                'tabId': self.tab_id,
                'script': script,
                'args': []
            }
        )
        return result

    @property
    def first(self):
        """Return self (for compatibility with Playwright locator.first)"""
        return self

    async def evaluate(self, script: str, *args):
        """Evaluate JavaScript on the located element"""
        full_script = f"""
        (function() {{
            const element = document.evaluate(
                '{self.selector.replace("xpath=", "")}',
                document,
                null,
                XPathResult.FIRST_ORDERED_NODE_TYPE,
                null
            ).singleNodeValue;
            if (element) {{
                return ({script})(element);
            }}
            return null;
        }})()
        """
        result = await send_extension_command(
            self.ws_manager,
            'EVALUATE',
            {
                'tabId': self.tab_id,
                'script': full_script,
                'args': list(args)
            }
        )
        return result
