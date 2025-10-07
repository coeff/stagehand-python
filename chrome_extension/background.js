// Stagehand Extension Background Script
// Handles CDP proxying and communication with Python server

const SERVER_URL = 'ws://localhost:8766';
let serverWs = null;
let reconnectAttempts = 0;
const MAX_RECONNECT_ATTEMPTS = 5;

// Track active debugger sessions
const activeSessions = new Map(); // tabId -> {attached: boolean, listeners: Set}

// Track pending requests
const pendingRequests = new Map(); // requestId -> {resolve, reject, timeout}

// CDP event listeners registry
const cdpEventListeners = new Map(); // tabId -> Map<eventName, Set<listenerId>>

console.log('[Stagehand] Background script loaded');

// Connect to Python WebSocket server
function connectToServer() {
  if (serverWs && (serverWs.readyState === WebSocket.OPEN || serverWs.readyState === WebSocket.CONNECTING)) {
    return;
  }

  console.log('[Stagehand] Connecting to server at', SERVER_URL);

  try {
    serverWs = new WebSocket(SERVER_URL);

    serverWs.onopen = () => {
      console.log('[Stagehand] Connected to Python server');
      reconnectAttempts = 0;

      // Send extension ready message
      sendToServer({
        type: 'EXTENSION_READY',
        timestamp: Date.now()
      });
    };

    serverWs.onmessage = async (event) => {
      try {
        const message = JSON.parse(event.data);
        await handleServerMessage(message);
      } catch (error) {
        console.error('[Stagehand] Error handling server message:', error);
      }
    };

    serverWs.onerror = (error) => {
      console.error('[Stagehand] WebSocket error:', error);
    };

    serverWs.onclose = () => {
      console.log('[Stagehand] Disconnected from server');
      serverWs = null;

      // Attempt to reconnect
      if (reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
        reconnectAttempts++;
        const delay = Math.min(1000 * Math.pow(2, reconnectAttempts), 10000);
        console.log(`[Stagehand] Reconnecting in ${delay}ms (attempt ${reconnectAttempts}/${MAX_RECONNECT_ATTEMPTS})`);
        setTimeout(connectToServer, delay);
      }
    };
  } catch (error) {
    console.error('[Stagehand] Error creating WebSocket:', error);
  }
}

// Send message to server
function sendToServer(message) {
  if (serverWs && serverWs.readyState === WebSocket.OPEN) {
    serverWs.send(JSON.stringify(message));
  } else {
    console.error('[Stagehand] Cannot send message - server not connected');
  }
}

// Handle messages from Python server
async function handleServerMessage(message) {
  const { id, type, tabId } = message;

  try {
    let result;

    switch (type) {
      case 'GET_ACTIVE_TAB':
        result = await getActiveTab();
        break;

      case 'ATTACH_DEBUGGER':
        result = await attachDebugger(tabId);
        break;

      case 'DETACH_DEBUGGER':
        result = await detachDebugger(tabId);
        break;

      case 'CDP_COMMAND':
        result = await sendCDPCommand(tabId, message.method, message.params);
        break;

      case 'EVALUATE':
        result = await evaluateScript(tabId, message.script, message.args);
        break;

      case 'NAVIGATE':
        result = await navigateTo(tabId, message.url, message.options);
        break;

      case 'CREATE_TAB':
        result = await createTab(message.url);
        break;

      case 'CLOSE_TAB':
        result = await closeTab(tabId);
        break;

      case 'GET_TAB_INFO':
        result = await getTabInfo(tabId);
        break;

      case 'GET_ALL_TABS':
        result = await getAllTabs();
        break;

      case 'SET_COOKIES':
        result = await setCookies(message.cookies);
        break;

      case 'GET_COOKIES':
        result = await getCookies(message.url);
        break;

      case 'INJECT_SCRIPT':
        result = await injectScript(tabId, message.script);
        break;

      case 'REGISTER_CDP_LISTENER':
        result = await registerCDPListener(tabId, message.eventName, message.listenerId);
        break;

      case 'UNREGISTER_CDP_LISTENER':
        result = await unregisterCDPListener(tabId, message.eventName, message.listenerId);
        break;

      case 'PONG':
        // Ignore PONG messages (keepalive response)
        return;

      default:
        throw new Error(`Unknown message type: ${type}`);
    }

    // Send response back
    sendToServer({
      id,
      type: 'RESPONSE',
      result,
      success: true
    });

  } catch (error) {
    console.error(`[Stagehand] Error handling ${type}:`, error);
    sendToServer({
      id,
      type: 'RESPONSE',
      error: error.message,
      stack: error.stack,
      success: false
    });
  }
}

// Get active tab
async function getActiveTab() {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  if (tabs.length === 0) {
    throw new Error('No active tab found');
  }
  return {
    tabId: tabs[0].id,
    url: tabs[0].url,
    title: tabs[0].title
  };
}

// Attach debugger to tab
async function attachDebugger(tabId) {
  try {
    // Check if already attached
    if (activeSessions.has(tabId) && activeSessions.get(tabId).attached) {
      console.log(`[Stagehand] Debugger already attached to tab ${tabId}`);
      return { attached: true, alreadyAttached: true };
    }

    await chrome.debugger.attach({ tabId }, '1.3');
    console.log(`[Stagehand] Debugger attached to tab ${tabId}`);

    activeSessions.set(tabId, {
      attached: true,
      listeners: new Set()
    });

    // Set up CDP event forwarding
    setupCDPEventForwarding(tabId);

    return { attached: true };
  } catch (error) {
    console.error(`[Stagehand] Failed to attach debugger to tab ${tabId}:`, error);
    throw error;
  }
}

// Detach debugger from tab
async function detachDebugger(tabId) {
  try {
    if (!activeSessions.has(tabId) || !activeSessions.get(tabId).attached) {
      return { detached: false, reason: 'Not attached' };
    }

    await chrome.debugger.detach({ tabId });
    console.log(`[Stagehand] Debugger detached from tab ${tabId}`);

    activeSessions.delete(tabId);
    cdpEventListeners.delete(tabId);

    return { detached: true };
  } catch (error) {
    console.error(`[Stagehand] Failed to detach debugger from tab ${tabId}:`, error);
    throw error;
  }
}

// Send CDP command
async function sendCDPCommand(tabId, method, params = {}) {
  try {
    // Ensure debugger is attached
    if (!activeSessions.has(tabId) || !activeSessions.get(tabId).attached) {
      await attachDebugger(tabId);
    }

    console.log(`[Stagehand] Sending CDP command to tab ${tabId}:`, method, params);

    const result = await chrome.debugger.sendCommand(
      { tabId },
      method,
      params
    );

    return result;
  } catch (error) {
    console.error(`[Stagehand] CDP command failed (${method}):`, error);
    throw error;
  }
}

// Setup CDP event forwarding to server
function setupCDPEventForwarding(tabId) {
  const listener = (source, method, params) => {
    if (source.tabId === tabId) {
      // Check if anyone is listening to this event
      const tabListeners = cdpEventListeners.get(tabId);
      if (tabListeners && tabListeners.has(method)) {
        sendToServer({
          type: 'CDP_EVENT',
          tabId,
          method,
          params,
          timestamp: Date.now()
        });
      }
    }
  };

  // Store listener reference
  if (!activeSessions.has(tabId)) {
    activeSessions.set(tabId, { attached: true, listeners: new Set() });
  }
  activeSessions.get(tabId).listeners.add(listener);

  chrome.debugger.onEvent.addListener(listener);
}

// Register CDP event listener
async function registerCDPListener(tabId, eventName, listenerId) {
  if (!cdpEventListeners.has(tabId)) {
    cdpEventListeners.set(tabId, new Map());
  }

  const tabListeners = cdpEventListeners.get(tabId);
  if (!tabListeners.has(eventName)) {
    tabListeners.set(eventName, new Set());
  }

  tabListeners.get(eventName).add(listenerId);
  console.log(`[Stagehand] Registered CDP listener for ${eventName} on tab ${tabId}`);

  return { registered: true };
}

// Unregister CDP event listener
async function unregisterCDPListener(tabId, eventName, listenerId) {
  const tabListeners = cdpEventListeners.get(tabId);
  if (tabListeners && tabListeners.has(eventName)) {
    tabListeners.get(eventName).delete(listenerId);

    // Clean up empty sets
    if (tabListeners.get(eventName).size === 0) {
      tabListeners.delete(eventName);
    }
  }

  return { unregistered: true };
}

// Evaluate script in tab
async function evaluateScript(tabId, script, args = []) {
  try {
    // Use chrome.scripting for Manifest V3
    // We need to inject the script directly, not use new Function
    const results = await chrome.scripting.executeScript({
      target: { tabId, allFrames: false },
      func: function(scriptText, scriptArgs) {
        // Use eval in the page context (not in extension context)
        // This is safe because it runs in the isolated content script world
        const func = eval(`(${scriptText})`);
        return func.apply(null, scriptArgs);
      },
      args: [script, args]
    });

    if (results && results.length > 0) {
      return results[0].result;
    }

    return null;
  } catch (error) {
    console.error(`[Stagehand] Script evaluation failed:`, error);
    throw error;
  }
}

// Navigate to URL
async function navigateTo(tabId, url, options = {}) {
  try {
    await chrome.tabs.update(tabId, { url });

    // Wait for navigation if requested
    if (options.waitUntil) {
      await waitForNavigation(tabId, options.waitUntil, options.timeout);
    }

    return { navigated: true, url };
  } catch (error) {
    console.error(`[Stagehand] Navigation failed:`, error);
    throw error;
  }
}

// Wait for navigation
async function waitForNavigation(tabId, waitUntil = 'load', timeout = 30000) {
  return new Promise((resolve, reject) => {
    const timeoutId = setTimeout(() => {
      reject(new Error('Navigation timeout'));
    }, timeout);

    const listener = (details) => {
      if (details.tabId === tabId) {
        // Check waitUntil condition
        if (waitUntil === 'commit' ||
            (waitUntil === 'domcontentloaded' && details.url) ||
            (waitUntil === 'load' && details.url) ||
            waitUntil === 'networkidle') {
          clearTimeout(timeoutId);
          chrome.webNavigation.onCompleted.removeListener(listener);
          resolve();
        }
      }
    };

    chrome.webNavigation.onCompleted.addListener(listener);
  });
}

// Create new tab
async function createTab(url) {
  const tab = await chrome.tabs.create({ url: url || 'about:blank' });
  return {
    tabId: tab.id,
    url: tab.url,
    title: tab.title
  };
}

// Close tab
async function closeTab(tabId) {
  await chrome.tabs.remove(tabId);

  // Clean up sessions
  if (activeSessions.has(tabId)) {
    await detachDebugger(tabId);
  }

  return { closed: true };
}

// Get tab info
async function getTabInfo(tabId) {
  const tab = await chrome.tabs.get(tabId);
  return {
    tabId: tab.id,
    url: tab.url,
    title: tab.title,
    active: tab.active,
    index: tab.index
  };
}

// Get all tabs
async function getAllTabs() {
  const tabs = await chrome.tabs.query({});
  return tabs.map(tab => ({
    tabId: tab.id,
    url: tab.url,
    title: tab.title,
    active: tab.active,
    index: tab.index
  }));
}

// Set cookies
async function setCookies(cookies) {
  const results = [];
  for (const cookie of cookies) {
    try {
      await chrome.cookies.set(cookie);
      results.push({ success: true, cookie });
    } catch (error) {
      results.push({ success: false, cookie, error: error.message });
    }
  }
  return results;
}

// Get cookies
async function getCookies(url) {
  const cookies = await chrome.cookies.getAll({ url });
  return cookies;
}

// Inject script into tab
async function injectScript(tabId, script) {
  try {
    const results = await chrome.scripting.executeScript({
      target: { tabId, allFrames: true },
      func: new Function(script)
    });
    return { injected: true, results: results.length };
  } catch (error) {
    console.error(`[Stagehand] Script injection failed:`, error);
    throw error;
  }
}

// Handle debugger detach events
chrome.debugger.onDetach.addListener((source, reason) => {
  console.log(`[Stagehand] Debugger detached from tab ${source.tabId}, reason:`, reason);

  if (activeSessions.has(source.tabId)) {
    activeSessions.delete(source.tabId);
    cdpEventListeners.delete(source.tabId);

    // Notify server
    sendToServer({
      type: 'DEBUGGER_DETACHED',
      tabId: source.tabId,
      reason
    });
  }
});

// Handle tab close events
chrome.tabs.onRemoved.addListener((tabId) => {
  if (activeSessions.has(tabId)) {
    activeSessions.delete(tabId);
    cdpEventListeners.delete(tabId);

    sendToServer({
      type: 'TAB_CLOSED',
      tabId
    });
  }
});

// Initialize connection on startup
connectToServer();

// Reconnect on browser startup
chrome.runtime.onStartup.addListener(() => {
  console.log('[Stagehand] Browser started, connecting to server');
  connectToServer();
});

// Keep service worker alive
let keepAliveInterval = setInterval(() => {
  if (serverWs && serverWs.readyState === WebSocket.OPEN) {
    sendToServer({ type: 'PING', timestamp: Date.now() });
  }
}, 20000); // Ping every 20 seconds

console.log('[Stagehand] Background script initialized');
