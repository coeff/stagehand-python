// Popup script to show extension status

const statusDiv = document.getElementById('status');
const connectionStatus = document.getElementById('connection-status');

// Check server connection status
async function checkStatus() {
  try {
    // Try to connect to the WebSocket server briefly
    const ws = new WebSocket('ws://localhost:8766');

    ws.onopen = () => {
      statusDiv.className = 'status connected';
      statusDiv.textContent = '✅ Connected to Python server';
      connectionStatus.textContent = 'Connected';
      ws.close();
    };

    ws.onerror = () => {
      statusDiv.className = 'status disconnected';
      statusDiv.textContent = '❌ Server not running';
      connectionStatus.textContent = 'Disconnected';
    };

    // Timeout after 2 seconds
    setTimeout(() => {
      if (ws.readyState === WebSocket.CONNECTING) {
        ws.close();
        statusDiv.className = 'status disconnected';
        statusDiv.textContent = '❌ Server not responding';
        connectionStatus.textContent = 'Timeout';
      }
    }, 2000);

  } catch (error) {
    statusDiv.className = 'status disconnected';
    statusDiv.textContent = '❌ Cannot connect to server';
    connectionStatus.textContent = 'Error';
  }
}

// Check status on load
checkStatus();

// Refresh every 5 seconds
setInterval(checkStatus, 5000);
