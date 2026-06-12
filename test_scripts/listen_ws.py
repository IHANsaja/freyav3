import asyncio
import json
import websockets

async def listen():
    uri = "ws://localhost:8000/ws"
    print(f"Connecting to {uri}...")
    try:
        async with websockets.connect(uri) as websocket:
            print("Connected to WebSocket server.")
            
            # Send start command
            start_cmd = {"type": "start"}
            print("Sending start command...")
            await websocket.send(json.dumps(start_cmd))
            
            # Listen to messages for 10 seconds
            print("Listening for events...")
            try:
                while True:
                    message = await asyncio.wait_for(websocket.recv(), timeout=10.0)
                    data = json.loads(message)
                    print(f"Received event: {data}")
            except asyncio.TimeoutError:
                print("Finished listening (timeout reached).")
    except Exception as e:
        print(f"WebSocket client error: {e}")

if __name__ == "__main__":
    asyncio.run(listen())
