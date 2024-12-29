import asyncio, logging, argparse, signal, sys
from at import AT
from irc import IRC

force_shutdown = False

async def shutdown(signal, loop, shutdown_event):
    global force_shutdown
    if shutdown_event.is_set():
        logging.info("Forcing exit...")
        sys.exit(1)
    
    logging.info(f"Received exit signal {signal.name}")
    shutdown_event.set()
    force_shutdown = True

async def main():
    parser = argparse.ArgumentParser(description='Bluesky IRC Bridge')
    parser.add_argument('-v', '--verbose', action='store_true', help='Enable verbose logging')
    parser.add_argument('-p', '--port', type=int, default=6667, help='Port to listen on (default: 6667)')
    args = parser.parse_args()

    logging_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=logging_level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    at = AT()
    try:
        logging.info("Initializing Bluesky client...")
        await at.initialize()
        logging.info("Bluesky client initialized successfully")
    except Exception as e:
        logging.error(f"Failed to initialize timeline: {e}")
        return

    async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        server = IRC(at, reader, writer)
        await server.handle_connection()

    shutdown_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(
            sig,
            lambda s=sig: asyncio.create_task(shutdown(s, loop, shutdown_event))
        )

    try:
        server = await asyncio.start_server(
            handle_client,
            "127.0.0.1",
            args.port
        )

        addrs = ", ".join(str(s.getsockname()) for s in server.sockets)
        logging.info(f"IRC Bridge running on {addrs}")
        
        async with server:
            await shutdown_event.wait()
            logging.info("Shutting down server...")
            server.close()
            
            try:
                await asyncio.wait_for(server.wait_closed(), timeout=2.0)
            except asyncio.TimeoutError:
                logging.warning("Shutdown timed out, forcing exit...")
                sys.exit(1)
    except Exception as e:
        logging.error(f"Server error: {e}")
    finally:
        logging.info("Server shutdown complete")
        if force_shutdown:
            sys.exit(0)

if __name__ == '__main__':
    asyncio.run(main())