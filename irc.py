import asyncio, logging, os
from typing import Optional, Dict, List
from at import AT, Author

SYNC_RATE = 30

class IRC:
    def __init__(self, at: AT, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.at = at
        self.reader = reader
        self.writer = writer

        self.joined_timeline = False
        self.running = True

        self.nick: Optional[str] = None  

        self.author_nicks: Dict[str, str] = {}  # handle -> nick
        self.authors: Dict[str, Author] = {}    # nick -> Author object
        self.joined_authors: Dict[str, bool] = {}  # nick -> whether they've joined #timeline

        self.addr = writer.get_extra_info('peername')
        logging.info(f"New connection from {self.addr}")
        self.server_name = os.getenv('IRC_SERVER_NAME', 'bridge.local')

        self.capabilities = set()
        self.cap_negotiating = False

        self.registered = False
        self.got_nick = False
        self.got_user = False
        self.joined_timeline = False

    async def handle_connection(self):
        try:
            self.send("NOTICE * :Welcome to the Bluesky IRC Bridge, JOIN #timeline")
            
            while self.running:
                try:
                    line = await self.reader.readline()
                    if not line:  # EOF
                        break
                    decoded = line.decode('utf-8', 'ignore').strip()
                    logging.debug(f"← {self.addr}: {decoded}")
                    await self.handle_line(decoded)
                except ConnectionError:
                    logging.warning(f"Connection lost from {self.addr}")
                    break
                except Exception as e:
                    logging.exception(f"Error handling line: {e}")
        finally:
            logging.info(f"Connection closed from {self.addr}")
            self.writer.close()
            await self.writer.wait_closed()

    async def handle_line(self, line):
        parts = line.split()
        if not parts:
            return

        cmd = parts[0].upper()
        if cmd == 'CAP':
            await self.handle_capability(parts[1:])
        elif cmd == 'PING':
            self.send(f"PONG {parts[1]}" if len(parts) > 1 else "PONG :")
        elif cmd == 'MODE':
            if len(parts) > 1:
                await self.handle_mode(parts[1], parts[2:] if len(parts) > 2 else [])
        elif cmd == 'NICK':
            old_nick = self.nick
            self.nick = parts[1] if len(parts) > 1 else 'anon'
            self.got_nick = True
            logging.info(f"Client {self.addr} nick change: {old_nick} → {self.nick}")
            if self.got_user:
                await self.finish_registration()
        elif cmd == 'USER':
            self.got_user = True
            if self.got_nick:
                await self.finish_registration()
        elif cmd == 'PRIVMSG' and self.joined_timeline:
            if len(parts) > 2 and parts[1] == '#timeline':
                msg = line.split(' ', 2)[2][1:] if len(line.split(' ', 2)) > 2 else ''
                await self.parse_timeline_cmd(msg)
        elif cmd == 'QUIT':
            self.running = False
        elif cmd == 'WHO' and len(parts) > 1:
            await self.handle_who(parts[1])
        elif cmd == 'WHOIS' and len(parts) > 1:
            await self.handle_whois(parts[1])
        elif cmd == 'NAMES' and len(parts) > 1:
            await self.handle_names(parts[1])

    async def finish_registration(self):
        if self.registered:
            return
            
        self.registered = True
        self.send(f":{self.server_name} 001 {self.nick} :Welcome to the Bluesky IRC Bridge, {self.nick}")
        self.send(f":{self.server_name} 002 {self.nick} :Running ATRelay IRC Bridge")
        self.send(f":{self.server_name} 003 {self.nick} :This server was created just now")
        self.send(f":{self.server_name} 004 {self.nick} {self.server_name} 1.0 o o")

        logging.info(f"Client {self.addr} auto-joined as {self.nick} to #timeline")
        self.joined_timeline = True
        self.send(f":{self.nick}!~@{os.getenv('BSKY_HANDLE')} JOIN #timeline")
        self.send(f":localhost 332 {self.nick} #timeline :Bluesky AT Bridge")
        await self.send_history()

    async def handle_capability(self, args):
        if not args:
            return
        
        subcmd = args[0].upper()
        if subcmd == 'LS':
            self.cap_negotiating = True
            self.send("CAP * LS :message-tags")
        elif subcmd == 'REQ' and len(args) > 1:
            requested = args[1].lstrip(':').split()
            if 'message-tags' in requested:
                self.capabilities.add('message-tags')
                self.send("CAP * ACK :message-tags")
        elif subcmd == 'END':
            self.cap_negotiating = False

    async def parse_timeline_cmd(self, msg: str) -> None:
        m = msg.strip().split()
        if not m:
            return

        cmd = m[0].lower()
        
        if cmd == '!echo' and len(m) > 1:
            self.send_channel(' '.join(m[1:]))
        else:
            self.send_channel("Commands: !echo <text>")

    def send(self, msg: str):
        try:
            logging.debug(f"→ {self.addr}: {msg}")
            self.writer.write(f"{msg}\r\n".encode())
        except Exception as e:
            logging.error(f"Error sending message: {e}")

    def send_tagged(self, msg: str, tags: Dict[str, str] = None):
        if tags and 'message-tags' in self.capabilities:
            escaped_tags = {
                k: v.replace('\\', '\\\\').replace(';', '\\:').replace(' ', '\\s')
                for k, v in tags.items()
            }
            tag_str = ';'.join(f"{k}={escaped_tags[k]}" for k, v in tags.items())
            msg = f"@{tag_str} {msg}"
        self.send(msg)

    def send_channel(self, msg: str):
        if self.nick:
            self.send(f":{self.nick}!~self@local PRIVMSG #timeline :{msg}")

    def ensure_author_joined(self, author: Author):
        if not self.joined_authors.get(author.nick):
            self.send(f":{author.nick}!@{author.handle} JOIN #timeline")
            self.joined_authors[author.nick] = True
            self.authors[author.nick] = author
            self.author_nicks[author.handle] = author.nick

    async def handle_who(self, target):
        if target != "#timeline":
            return
        
        for nick, author in self.authors.items():
            flags = "H"  # H for "here"
            self.send(f":{self.server_name} 352 {self.nick} #timeline * {author.handle} {nick} {flags} :0 {author.display_name or author.handle}")
        self.send(f":{self.server_name} 315 {self.nick} #timeline :End of WHO list")

    async def handle_whois(self, nick):
        author = self.authors.get(nick)
        if not author:
            self.send(f":{self.server_name} 401 {self.nick} {nick} :No such nick")
            return
        
        self.send(f":{self.server_name} 311 {self.nick} {nick} * {author.handle} * :{author.display_name or author.handle}")
        self.send(f":{self.server_name} 319 {self.nick} {nick} :#timeline")
        
        self.send(f":{self.server_name} 320 {self.nick} {nick} :Bluesky ID: {author.did}")
        self.send(f":{self.server_name} 320 {self.nick} {nick} :Handle: @{author.handle}")
        if author.display_name:
            self.send(f":{self.server_name} 320 {self.nick} {nick} :Display Name: {author.display_name}")
        
        self.send(f":{self.server_name} 318 {self.nick} {nick} :End of WHOIS list")

    async def handle_names(self, target):
        if target != "#timeline":
            return
        
        names = list(self.authors.keys())
        chunk_size = 20
        for i in range(0, len(names), chunk_size):
            chunk = names[i:i + chunk_size]
            self.send(f":{self.server_name} 353 {self.nick} = #timeline :{' '.join(chunk)}")
        self.send(f":{self.server_name} 366 {self.nick} #timeline :End of NAMES list")

    async def send_history(self):
        if not self.at.posts:
            self.send_channel("No posts.")
            return
        for post in sorted(self.at.posts, key=lambda p: p._at):
            await self.send_post_as_author(post)

    async def send_post_as_author(self, post):
        author = self.at.get_author(post)
        self.ensure_author_joined(author)

        tags = {
            'time': post._at.strftime('%Y-%m-%dT%H:%M:%S.000Z')
        }

        lines = self.at.format_post_for_irc(post)
        for line in lines:
            self.send_tagged(f":{author.nick}!@{self.server_name} PRIVMSG #timeline :{line}", tags)

    async def handle_mode(self, target, args):
        if target == "#timeline":
            self.send(f":{self.server_name} 324 {self.nick} #timeline +nt")
        elif target == self.nick:
            self.send(f":{self.server_name} 221 {self.nick} +")

    async def shutdown(self):
        self.running = False
        if self.writer:
            try:
                self.send("ERROR :Server shutting down")
                self.writer.close()
                await self.writer.wait_closed()
            except:
                pass