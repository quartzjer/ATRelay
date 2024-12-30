# ATRelay - Bluesky IRC Bridge

ATRelay is a bridge that connects Bluesky's AT Protocol to IRC, allowing you to follow your Bluesky timeline through any IRC client.

## Features

- Real-time Bluesky timeline in IRC format
- Auto-join of #timeline channel
- Rich post formatting:
  - Reposts shown with proper attribution and indentation
  - Reply threading indicators
  - Image embeds with alt text
  - Video embeds with direct links
  - Link extraction and display
  - Quote posts with proper nesting
- Basic IRC command support:
  - WHO - List all users in the timeline
  - WHOIS - Get detailed Bluesky user information
  - NAMES - Get channel member list
  - MODE - Channel and user modes
- Proper nick handling with sanitized Bluesky handles
- Automatic timeline synchronization every 30 seconds

## Screenshots

[Screenshot of HexChat](media/HexChat.png)

[Screenshot of Srain](media/Srain.png)

[Screenshot of Textual](media/Textual.png)

## Installation

1. Clone the repository:
```bash
git clone https://github.com/quartzjer/ATRelay.git
cd ATRelay
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Create a `.env` file with your Bluesky credentials:
```env
BSKY_HANDLE=you.bsky.social
BSKY_APP_PASSWORD=your-app-password
```

4. Run the server:
```bash
python server.py
```

By default, the server runs on localhost:6667. Use `-p` to specify a different port and `-v` for verbose logging.

## Usage

1. Connect to localhost:6667 with your IRC client
2. You should automatically join #timeline with the recent timeline
3. Watch your latest Bluesky timeline updates appear

## TODO

- [ ] Support for multiple channels (different feeds/lists)
- [ ] Post creation support
- [ ] Open any post as a channel to interact with replies
- [ ] Like/Repost functionality through commands
- [ ] DMs
- [ ] Notifications

## Contributing

Pull requests are encouraged! For major changes, please open an issue first to discuss what you would like to change.

## License

[MIT](LICENSE)
