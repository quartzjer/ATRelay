import asyncio, logging, argparse, signal
from at import AT
from irc import IRC

VERSION = "0.1.0"

class IRCServer:
    def __init__(self, at: AT, host: str, port: int):
        self.at = at
        self.host = host
        self.port = port
        self.version = VERSION
        self.clients = set()
        self.server = None
        self._sync_task = None

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        client = IRC(self.at, reader, writer, version=self.version)
        self.clients.add(client)
        try:
            await client.handle_connection()
        finally:
            self.clients.discard(client)

    async def sync_timeline(self):
        while True:
            try:
                new_posts = await self.at.sync_timeline()
                for client in list(self.clients):
                    for post in new_posts:
                        await client.send_post_as_author(post)
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                break

    async def start(self):
        self.server = await asyncio.start_server(
            self.handle_client,
            self.host,
            self.port
        )
        self._sync_task = asyncio.create_task(self.sync_timeline())
        
        addrs = ', '.join(str(sock.getsockname()) for sock in self.server.sockets)
        logging.info(f'IRC Bridge running on {addrs}')
        
        async with self.server:
            await self.server.serve_forever()

    async def shutdown(self):
        if self._sync_task:
            self._sync_task.cancel()
            await self._sync_task
            
        for client in list(self.clients):
            await client.shutdown()
            
        if self.server:
            self.server.close()
            await self.server.wait_closed()

async def main():
    parser = argparse.ArgumentParser(description='Bluesky IRC Bridge')
    parser.add_argument('-v', '--verbose', action='store_true')
    parser.add_argument('-p', '--port', type=int, default=6667)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    logging.info(f"ATRelay version {VERSION} starting up")

    at = AT()
    await at.initialize()

    server = IRCServer(at, "127.0.0.1", args.port)
    
    def handle_signal():
        asyncio.create_task(server.shutdown())
    
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, handle_signal)

    try:
        await server.start()
    except asyncio.CancelledError:
        logging.info("Server shutdown initiated")
    finally:
        await server.shutdown()
        logging.info("Server shutdown complete")

if __name__ == '__main__':
    asyncio.run(main())