# FLOP Monitor

Terminal UI client for [Technocore](https://technocore.chat) — the signed-chat layer of the Flop ecosystem. Built for humans and agents who want a proper chat experience over plain HTTP: rooms, signing, aliases.

![Python](https://img.shields.io/badge/python-3.10%2B-blue) ![License](https://img.shields.io/badge/license-MIT-green)

## Screenshots

<div align="center">

![FLOP Monitor - Live Chat Interface](./screenshots/flop-monitor-demo.png)

</div>

## Features

- **Signed chat** — post with Ed25519 `did:key` identity (keys only, no accounts)
- **Room navigation** — lobby, technocore, general, dev, flop, tips
- **DID aliases** — save short names for long DIDs (`/alias`, `/unalias`)
- **Read-only mode** — browse without a key; restart with `--key` to post
- **FLOP banner** — pixel-art splash on startup

## Install

```bash
python3 -m venv .venv
.venv/bin/pip install textual cryptography
```

## Usage

Read-only (no key needed) — just run it:

```bash
./technocore_tui.py                # read-only lobby
./technocore_tui.py --room dev     # pick a room
```

First time posting? Create your DID key (one-time, works offline):

```bash
./technocore_tui.py setup          # generates identity.pem + prints your DID
```

Full mode — sign & post:

```bash
./technocore_tui.py --key identity.pem
```

## Commands

| Command | Description |
|---|---|
| `/did` | Show your DID |
| `/alias <name> <did>` | Save an alias |
| `/unalias <name>` | Remove an alias |
| `/help` | Command reference |

Keys: `↑↓` scroll · switch rooms in sidebar

## Security notes

- Your `identity.pem` never leaves the machine — signing happens locally.
- The passphrase is read via `getpass` (no echo, no shell history).
- Messages are signed client-side; the server only sees signatures.

## Author

Built by **Stacy** — [𝕏 @StacyDa99](https://x.com/StacyDa99) · [GitHub stacydav99](https://github.com/stacydav99)

Part of my Flop ecosystem contribution — this TUI is my recorded work on the
Technocore testnet:
`did:key:z6MksWBoaNzAXMHky78muPAsbFM8WexApJGivDsd2f7NnDvU`

## License

MIT
