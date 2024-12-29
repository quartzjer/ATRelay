import asyncio, logging, time
from datetime import datetime
from typing import Optional, Dict, List
from at import AT, Author

PAGE_SIZE = 50

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
        self.server_name = "bridge"

        self.capabilities = set()
        self.cap_negotiating = False

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
        elif cmd == 'NICK':
            old_nick = self.nick
            self.nick = parts[1] if len(parts) > 1 else 'anon'
            logging.info(f"Client {self.addr} nick change: {old_nick} → {self.nick}")
        elif cmd == 'USER':
            pass
        elif cmd == 'JOIN':
            if len(parts) > 1 and parts[1] == '#timeline':
                logging.info(f"Client {self.nick} joined #timeline")
                self.joined_timeline = True
                self.send(f":{self.nick}!~user@local JOIN #timeline")
                self.send(f":localhost 332 {self.nick} #timeline :Bluesky AT Bridge")
                # Once joined, push the first page of posts into IRC
                await self.send_posts(page=1)
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
        
        if cmd == '!page' and len(m) > 1 and m[1].isdigit():
            page_num = int(m[1])
            await self.send_posts(page_num)

        elif cmd == '!detail' and len(m) > 1 and m[1].isdigit():
            n = int(m[1])
            fv = self.at.find_feed_view(n)
            if not fv:
                self.send_channel(f"No post found for #{n}")
                return
            # Send full detail from the author
            await self.send_post_as_author(fv)

        elif cmd == '!refresh':
            await self.do_refresh()

        else:
            self.send_channel("Commands: !page N, !detail N, !refresh")

    def send(self, msg: str):
        try:
            logging.debug(f"→ {self.addr}: {msg}")
            self.writer.write(f"{msg}\r\n".encode())
        except Exception as e:
            logging.error(f"Error sending message: {e}")

    def send_tagged(self, msg: str, tags: Dict[str, str] = None):
        if tags and 'message-tags' in self.capabilities:
            tag_str = ' '.join(f"{k}={v}" for k, v in tags.items())
            msg = f"@{tag_str} {msg}"
        self.send(msg)

    def send_channel(self, msg: str, timestamp: datetime = None):
        if self.nick:
            tags = {}
            if timestamp:
                ts = timestamp.timestamp()
                tags['time'] = datetime.utcfromtimestamp(ts).strftime('%Y-%m-%dT%H:%M:%S.000Z')
            self.send_tagged(f":{self.nick}!~self@local PRIVMSG #timeline :{msg}", tags)

    def ensure_author_joined(self, author: Author):
        if not self.joined_authors.get(author.nick):
            self.send(f":{author.nick}@{author.handle} JOIN #timeline")
            self.joined_authors[author.nick] = True
            self.authors[author.nick] = author
            self.author_nicks[author.handle] = author.nick

    async def handle_who(self, target):
        if target != "#timeline":
            return
        
        for nick, author in self.authors.items():
            flags = "H"  # H for "here"
            self.send(f":localhost 352 {self.nick} #timeline user {author.handle} {nick} {flags} :0 {author.display_name or author.handle}")
        self.send(f":localhost 315 {self.nick} #timeline :End of WHO list")

    async def handle_whois(self, nick):
        author = self.authors.get(nick)
        if not author:
            self.send(f":localhost 401 {self.nick} {nick} :No such nick")
            return
        
        self.send(f":localhost 311 {self.nick} {nick} user {author.handle} * :{author.display_name or author.handle}")
        self.send(f":localhost 319 {self.nick} {nick} :#timeline")
        
        self.send(f":localhost 320 {self.nick} {nick} :Bluesky ID: {author.did}")
        self.send(f":localhost 320 {self.nick} {nick} :Handle: @{author.handle}")
        if author.display_name:
            self.send(f":localhost 320 {self.nick} {nick} :Display Name: {author.display_name}")
        
        self.send(f":localhost 318 {self.nick} {nick} :End of WHOIS list")

    async def send_posts(self, page: int):
        posts = self.at.get_post_list(page, page_size=PAGE_SIZE)
        if not posts:
            self.send_channel("No posts to show on that page.")
            return
        for fv in posts:
            await self.send_post_as_author(fv)

    async def send_post_as_author(self, fv):
        author = self.at.get_author(fv)
        self.ensure_author_joined(author)

        timestamp = datetime.fromisoformat(fv.post.record.created_at.replace('Z', '+00:00'))
        tags = {
            'time': timestamp.strftime('%Y-%m-%dT%H:%M:%S.000Z')
        }

        lines = self.at.format_post_for_irc(fv)
        for _, line in enumerate(lines):
            self.send_tagged(f":{author.nick}!@{self.server_name} PRIVMSG #timeline :{line}", tags)

    async def do_refresh(self):
        await self.at.fetch_timeline()
        self.send_channel("AT refreshed.")