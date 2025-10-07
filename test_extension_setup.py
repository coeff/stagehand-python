#!/usr/bin/env python3
"""
Quick test script to verify extension setup

This script checks:
1. WebSocket server is running
2. Can connect to server
3. Extension is loaded (if Python connects successfully)

Run this before running actual Stagehand examples.
"""

import asyncio
import websockets


async def test_connection():
    print("\n🧪 Testing Stagehand Extension Setup")
    print("=" * 50)

    # Test 1: Can we connect to the server?
    print("\n1️⃣  Testing server connection...")
    try:
        ws = await asyncio.wait_for(
            websockets.connect("ws://localhost:8766"),
            timeout=5.0
        )
        print("   ✅ Connected to WebSocket server")

        # Send a test message (so server knows we're a Python client, not extension)
        import json
        await ws.send(json.dumps({'type': 'TEST'}))

        # Wait for welcome message
        try:
            welcome = await asyncio.wait_for(ws.recv(), timeout=5.0)
            print(f"   ✅ Received welcome message")
            print(f"      {welcome[:100]}...")

            # Check if extension is connected
            import json
            data = json.loads(welcome)
            if data.get('extension_connected'):
                print("   ✅ Chrome extension is connected!")
            else:
                print("   ⚠️  Chrome extension is NOT connected")
                print("      Make sure extension is loaded in Chrome:")
                print("      1. Go to chrome://extensions/")
                print("      2. Enable 'Developer mode'")
                print("      3. Click 'Load unpacked'")
                print("      4. Select chrome_extension/ folder")

        except asyncio.TimeoutError:
            print("   ❌ No welcome message received")
            print("      Server may not be running correctly")
            await ws.close()
            return False

        await ws.close()
        print("   ✅ Connection test passed!")
        return True

    except asyncio.TimeoutError:
        print("   ❌ Connection timeout")
        print("      Is the server running?")
        print("      Start it with: python server/extension_server.py")
        return False
    except ConnectionRefusedError:
        print("   ❌ Connection refused")
        print("      Server is not running!")
        print("      Start it with: python server/extension_server.py")
        return False
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False


async def main():
    success = await test_connection()

    print("\n" + "=" * 50)
    if success:
        print("✅ Setup looks good!")
        print("\nNext steps:")
        print("1. Make sure extension is loaded in Chrome")
        print("2. Run: python examples/extension_example.py")
    else:
        print("❌ Setup incomplete")
        print("\nTroubleshooting:")
        print("1. Start server: python server/extension_server.py")
        print("2. Load extension in Chrome (see START_EXTENSION_MODE.md)")
        print("3. Run this test again")

    print()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nTest cancelled by user")
