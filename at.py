import os, re
from dotenv import load_dotenv
from atproto import AsyncClient
from typing import Optional, Dict, List

load_dotenv()

def sanitize(field: str) -> str:
    field = re.sub(r'\.bsky\.social$', '', field)
    field = field.replace('.', '_')
    field = field.replace(' ', '_')
    # strip out anything but letters, digits, and underscores
    base = re.sub(r'[^A-Za-z0-9_]', '', field)
    if not base:
        base = "_nohandle"
    if base[0].isdigit():
        base = "_" + base
    return base[:16]

class Author:
    def __init__(self, did: str, handle: str, display_name: Optional[str] = None):
        self.did = did
        self.handle = handle
        self.display_name = display_name
        self.nick = sanitize(display_name or handle)

class AT:
    def __init__(self):
        self.client = AsyncClient()
        self.handle = os.getenv('BSKY_HANDLE')
        self.password = os.getenv('BSKY_APP_PASSWORD')
        self.profile = None

        # Raw feed data
        self.timeline = []  
        self.post_index = {}

        self.initialized = False

    async def initialize(self):
        self.profile = await self.client.login(self.handle, self.password)
        await self.fetch_timeline()
        self.initialized = True

    async def fetch_timeline(self):
        data = await self.client.get_timeline(algorithm='reverse-chronological')
        self.timeline = data.feed
        self.post_index = {
            i + 1: {'cid': fv.post.cid, 'uri': fv.post.uri}
            for i, fv in enumerate(self.timeline)
        }

    def find_feed_view(self, n: int):
        pi = self.post_index.get(n)
        if not pi:
            return None
        for fv in self.timeline:
            if fv.post.cid == pi['cid']:
                return fv
        return None

    def get_post_list(self, page: int = 1, page_size: int = 10) -> List:
        start = (page - 1) * page_size
        end = start + page_size
        return self.timeline[start:end]

    def get_author(self, fv) -> Author:
        # Get author from either repost reason or post author
        author = getattr(getattr(fv, 'reason', None), 'by', None) or fv.post.author
        return Author(
            did=author.did,
            handle=author.handle,
            display_name=getattr(author, 'display_name', None)
        )

    def format_post_for_irc(self, fv):
        lines = []
        post = fv.post
        if post.record.reply:
            return [] #ignore for now since we need to go get the replied-to post for context

        print(post.model_dump_json())

        formatted_lines = self.format_post(post.record)
        formatted_lines.extend(self.format_embed(post.embed, post.uri))
        if len(formatted_lines) == 2:
            formatted_lines[:] = [' '.join(formatted_lines)]
    
        # Handle reposts showing original author and indented
        if hasattr(fv, 'reason') and hasattr(fv.reason, 'by'):
            lines.append(f"↻ @{post.author.handle}:")
            lines.extend(f" | {line}" for line in formatted_lines)
        else:
            lines.extend(formatted_lines)

        return lines

    def format_post(self, record):
        text = (record.text or '(no text)').strip()
        
        lines = re.split(r'\r\n|\r|\n', text)
        lines = [line for line in lines if line.strip()]

        facet_links = []
        if hasattr(record, 'facets') and record.facets:
            for facet in record.facets:
                if facet.py_type == 'app.bsky.richtext.facet':
                    for feature in facet.features:
                        if feature.py_type == 'app.bsky.richtext.facet#link':
                            facet_links.append(feature.uri)

        lines[-1] += " " + " ".join(facet_links)
        return lines

    def format_embed(self, e, uri):
        if not e:
            return []
        
        if e.py_type == 'app.bsky.embed.images#view':
            lines = []
            for x in e.images:
                alt_text = f"{x.alt.replace('\n',' ').strip()} " if getattr(x, 'alt', None) else ""
                lines.append(f"📷 {alt_text}{x.fullsize or x.thumb} ")
            return lines
        elif e.py_type == 'app.bsky.embed.record#view':
            if hasattr(e.record, 'value'):
                formatted_lines = self.format_post(e.record.value)
                formatted_lines.extend(self.format_embed(e.record.value.embed, e.record.uri))
                lines = [f"💬 @{e.record.author.handle}:"]
                lines.extend(f" | {line}" for line in formatted_lines)
                return lines
        elif 'external' in e.py_type:
            return [f"🔗 {e.external.uri}"]
        elif e.py_type == 'app.bsky.embed.video#view':
            alt_text = f"{e.alt.replace('\n',' ').strip()} " if getattr(e, 'alt', None) else ""
            # use the atproto browser site for the video player
            did_match = re.search(r'did:plc:[^/]+', uri)
            if did_match and e.cid:
                did = did_match.group(0)
                video_url = f"https://atproto-browser.vercel.app/blob/{did}/{e.cid}"
                return [f"🎥 {alt_text}{video_url}"]
            return []

        return []