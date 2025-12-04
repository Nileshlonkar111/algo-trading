#!/usr/bin/env python3
"""
WebSocket Connection Test Script
Tests the /ws endpoint with a proper WebSocket client
"""
import asyncio
import websockets
import json
import sys

async def test_websocket():
    uri = "ws://localhost:8000/ws"
    
    print(f"Connecting to {uri}...")
    
    try:
        async with websockets.connect(uri) as websocket:
            print("✅ WebSocket connection established successfully!")
            
            # Wait for initial message
            print("\nWaiting for initial dashboard update...")
            message = await asyncio.wait_for(websocket.recv(), timeout=10)
            data = json.loads(message)
            
            print(f"✅ Received initial message:")
            print(f"   Type: {data.get('type')}")
            print(f"   Trading Active: {data.get('data', {}).get('trading', {}).get('active')}")
            print(f"   Authenticated: {data.get('data', {}).get('trading', {}).get('authenticated')}")
            
            # Listen for a few more updates
            print("\nListening for updates (5 seconds)...")
            for i in range(3):
                try:
                    message = await asyncio.wait_for(websocket.recv(), timeout=5)
                    data = json.loads(message)
                    print(f"✅ Update {i+1}: {data.get('type')}")
                except asyncio.TimeoutError:
                    print(f"   No update received in iteration {i+1}")
            
            print("\n✅ WebSocket test completed successfully!")
            print("   The WebSocket endpoint is working correctly.")
            return True
            
    except websockets.exceptions.InvalidStatusCode as e:
        print(f"❌ Connection failed with status code: {e.status_code}")
        print(f"   This might indicate the endpoint doesn't exist or is misconfigured")
        return False
    except asyncio.TimeoutError:
        print("❌ Timeout waiting for server response")
        print("   The connection was established but no data received")
        return False
    except ConnectionRefusedError:
        print("❌ Connection refused")
        print("   Make sure the server is running on localhost:8000")
        return False
    except Exception as e:
        print(f"❌ Error: {type(e).__name__}: {e}")
        return False

if __name__ == "__main__":
    print("WebSocket Connection Test")
    print("=" * 50)
    
    result = asyncio.run(test_websocket())
    sys.exit(0 if result else 1)