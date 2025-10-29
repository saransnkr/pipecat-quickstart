import asyncio
import websockets
import json
from pipecat.transports.base_transport import BaseTransport
from pipecat.frames.frames import AudioRawFrame

class WebSocketTransport(BaseTransport):
    def __init__(self, host="0.0.0.0", port=8765, **kwargs):
        super().__init__(**kwargs)
        self.host = host
        self.port = port
        self.clients = set()

    async def input(self):
        """Incoming audio from the client (microphone)."""
        queue = asyncio.Queue()

        async def handler(websocket, path):
            self.clients.add(websocket)
            print(f"✅ Client connected: {websocket.remote_address}")
            try:
                async for message in websocket:
                    if isinstance(message, bytes):
                        # Raw PCM 16-bit audio chunk
                        await queue.put(AudioRawFrame(message))
                    else:
                        data = json.loads(message)
                        print("📩 Received JSON:", data)
            except websockets.ConnectionClosed:
                print(f"❌ Client disconnected: {websocket.remote_address}")
            finally:
                self.clients.remove(websocket)

        self.server = await websockets.serve(handler, self.host, self.port)
        print(f"🚀 WebSocket server running on ws://{self.host}:{self.port}")

        while True:
            yield await queue.get()


async def output(self):
    """Send bot TTS audio back to all connected clients."""
    while True:
        frame = await self.output_queue.get()
        if isinstance(frame, AudioRawFrame):
            # Send binary audio data to the client
            for client in list(self.clients):
                try:
                    await client.send(frame.data)
                except:
                    pass

