#!/usr/bin/env python3
"""FLOP Monitor v1 — signed chat terminal client for Technocore.

Layout: styled startup banner (pixel-art title, subtitle, author credit,
status line — or banner.txt pixel logo if present), room sidebar,
threaded chat feed, hairline prompt input, split status bar. English UI.
"""

from __future__ import annotations
import os
import sys

# Auto-use local .venv when textual isn't installed on the system python,
# so `./technocore_tui.py` just works after a plain git clone + venv setup.
if __package__ is None:
    _here = os.path.dirname(os.path.abspath(__file__))
    _venv_py = os.path.join(_here, ".venv", "bin", "python")
    try:
        import textual  # noqa: F401
    except ImportError:
        if os.path.exists(_venv_py) and sys.executable != _venv_py:
            os.execv(_venv_py, [_venv_py] + sys.argv)


import asyncio
import argparse
import base64
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

from textual import events, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Input, Rule, Static

try:
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
except ImportError:
    load_pem_private_key = None

BASE = "https://technocore.chat"
BG = "#1a1a1e"
FG = "#e8e6e3"
DIM = "#6b6b75"
ACCENT = "#ea6e2c"   # flop orange
WHITE = "#f0f0f0"
HAIRLINE = "#2a2a31"  # subtle separators
BORDER = "#3a3a42"    # box border (a bit brighter than hairline)
FOOT_BG = "#14141a"

VERSION = "v1"
SUBTITLE = "signed chat for humans — keys only, no accounts"
AUTHOR = "by https://github.com/stacydav99"

BANNER_FILE = Path(__file__).parent / "flop_banner.ansi"


def b58(data: bytes) -> str:
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    n = int.from_bytes(data)
    out = ""
    while n > 0:
        n, r = divmod(n, 58)
        out = alphabet[r] + out
    for b in data:
        if b == 0:
            out = "1" + out
        else:
            break
    return out


def did_from_key(key) -> str:
    pub = key.public_key().public_bytes_raw()
    return "did:key:" + "z" + b58(b"\xed\x01" + pub)


def sign_payload(key, payload: bytes) -> str:
    return base64.urlsafe_b64encode(key.sign(payload)).decode().rstrip("=")


def message_payload(room: str, nonce: str, text: str) -> bytes:
    return f"{room}|{nonce}|{' '.join(text.split())}".encode()


def http_json(url: str, timeout: float = 15.0):
    req = urllib.request.Request(url, headers={"User-Agent": "flop-monitor/1"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def post_message(room: str, text: str, key):
    nonce = str(time.time_ns())
    payload = message_payload(room, nonce, text)
    body = json.dumps({
        "did": did_from_key(key),
        "sig": sign_payload(key, payload),
        "nonce": nonce,
        "text": " ".join(text.split()),
    }).encode()
    url = f"{BASE}/r/{urllib.parse.quote(room)}?format=json"
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "flop-monitor/1"},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        resp = json.load(r)
    posted = resp.get("posted") or {}
    if posted.get("text") != " ".join(text.split()):
        raise RuntimeError("server response mismatch")
    return posted


def esc(s: str) -> str:
    return s.replace("[", "\\[")


def banner_markup(line: str, row_colors: list) -> str:
    """Run-length encode one banner row into Textual markup.

    Spaces must be emitted verbatim (no color tags) — dropping them
    merges adjacent glyphs.
    """
    parts = []
    run_ch, run_col, start = None, None, 0
    for col, ch in enumerate(line):
        c = row_colors[col] if col < len(row_colors) else None
        if ch != run_ch or c != run_col:
            if run_ch is not None:
                seg = line[start:col]
                if run_ch == " ":
                    parts.append(seg)
                elif run_col:
                    parts.append(f"[{run_col}]{seg}[/]")
                else:
                    parts.append(seg)
            run_ch, run_col, start = ch, c, col
    if run_ch is not None:
        seg = line[start:]
        if run_ch == " ":
            parts.append(seg)
        elif run_col:
            parts.append(f"[{run_col}]{seg}[/]")
        else:
            parts.append(seg)
    return "".join(parts)


# 4x6 pixel glyphs for the built-in startup title (chunky pixel style,
# matches the FLOP logo aesthetic). Covers "FLOP MONITOR".
PIXEL_FONT = {
    "F": ["XXXX", "X...", "XXX.", "X...", "X...", "X..."],
    "L": ["X...", "X...", "X...", "X...", "X...", "XXXX"],
    "O": [".XX.", "X..X", "X..X", "X..X", "X..X", ".XX."],
    "P": ["XXX.", "X..X", "X..X", "XXX.", "X...", "X..."],
    "M": ["X..X", "XX.X", "X.XX", "X..X", "X..X", "X..X"],
    "N": ["X..X", "XX.X", "XX.X", "X.XX", "X.XX", "X..X"],
    "I": [".XX.", ".XX.", ".XX.", ".XX.", ".XX.", ".XX."],
    "T": ["XXXX", ".XX.", ".XX.", ".XX.", ".XX.", ".XX."],
    "R": ["XXX.", "X..X", "X..X", "XXX.", "X.X.", "X..X"],
}


def render_pixel_title(text: str) -> list[str]:
    """Render text as 6 markup rows, one full-block █ per pixel.

    Full blocks only — half-blocks (▀▄) depend on terminal font and
    shatter on some setups. Letters wrapped individually so per-letter
    colors never bleed.
    """
    rows = []
    for r in range(6):
        parts = []
        for ch in text:
            glyph = PIXEL_FONT.get(ch)
            if glyph is None:
                seg = "    "
            else:
                seg = "".join("█" if glyph[r][col] == "X" else " "
                              for col in range(4))
            parts.append(f"[{ACCENT}]{seg}[/]" if ch == "O" else seg)
            parts.append(" ")
        rows.append("".join(parts).rstrip())
    return rows


class TechnocoreTUI(App):
    CSS = f"""
    Screen {{ background: {BG}; }}

    #header {{
        height: auto;
        padding: 0 3 1 3;
        background: {BG};
        scrollbar-size: 0 0;
        border: solid {BORDER};
        border-title-color: {ACCENT};
        border-title-background: {BG};
        border-title-style: bold;
        margin-bottom: 1;
    }}
    .banner {{ color: {WHITE}; }}
    .subtitle {{ color: {FG}; margin-top: 1; }}
    .credit {{ color: {DIM}; }}
    .banner-status {{ color: {DIM}; margin-bottom: 1; }}

    #main {{ height: 1fr; margin-bottom: 1; }}

    #sidebar {{
        width: 24; padding: 1 1;
        background: {FOOT_BG};
        border: solid {BORDER};
        border-title-color: {ACCENT};
        border-title-background: {FOOT_BG};
        border-title-style: bold;
        scrollbar-size: 0 0;
        margin-right: 1;
    }}
    .sidebar-head {{ display: none; }}
    .room-item {{ color: {FG}; padding: 0 1; }}
    .room-item:hover {{ background: #23232b; }}

    #feed {{
        width: 1fr; height: 1fr; padding: 0 3;
        background: {BG};
        border: solid {BORDER};
        border-title-color: {FG};
        border-title-background: {BG};
        border-title-style: bold;
        scrollbar-size: 0 0;
    }}
    .welcome {{ color: {WHITE}; text-style: bold; }}
    .whatsnew-head {{ color: {DIM}; text-style: bold; }}
    .whatsnew {{ color: {FG}; }}
    #feed > Rule {{ color: {HAIRLINE}; margin-top: 1; margin-bottom: 1; }}

    .msg {{ margin-bottom: 1; }}

    #help-pop {{
        position: absolute;
        width: 48; height: auto; max-height: 12;
        background: #23232b;
        border: solid {BORDER};
        padding: 1 2;
        color: #9aa0a6;
        display: none;
    }}
    #live-clock {{
        position: absolute;
        width: 100%; height: 1;
        background: {BG};
        color: {DIM};
        text-align: right;
        padding-right: 2;
    }}
    #help-pop.visible {{ display: block; }}
    .help-title {{ color: #8aa08a; text-style: bold; }}

    #input {{
        dock: bottom; height: 5; padding: 1 2;
        background: {BG};
        border: solid {BORDER};
        border-title-color: {DIM};
        border-title-background: {BG};
    }}
    #input > .input--placeholder {{ color: {DIM}; }}

    #statusbar {{
        dock: bottom; height: 1;
        padding: 0 3;
        background: {FOOT_BG};
    }}
    #status-left {{ width: 1fr; color: {DIM}; }}
    #status-right {{ width: auto; color: {DIM}; }}
    #footer {{
        dock: bottom; height: 1;
        padding: 0 3;
        background: {FOOT_BG};
        color: {DIM};
        text-align: center;
    }}
    """
    BINDINGS = [
        ("ctrl+c", "quit", "Quit"),
        ("ctrl+r", "refresh", "Refresh"),
        ("escape", "hide_help", "Close help"),
        ("up", "scroll_up", "Scroll up"),
        ("down", "scroll_down", "Scroll down"),
        ("pageup", "page_up", "Page up"),
        ("pagedown", "page_down", "Page down"),
        ("home", "scroll_home", "Top"),
        ("end", "scroll_end", "Bottom"),
    ]

    def __init__(self, room: str, key=None, sidebar_width: int = 24):
        super().__init__()
        self.room = room
        self.key = key
        self.sidebar_width = max(8, min(int(sidebar_width), 60))
        self.last_seq = None
        self.my_did = did_from_key(key) if key else None
        self.head_seq = 0
        self._help_timer = None
        self.load_aliases()

    def _show_help(self):
        self._position_help()
        pop = self.query_one("#help-pop")
        pop.update(
            "[#8aa08a][b]Commands[/][/]\n"
            "[#9aa0a6]  /join <room>       switch room[/]\n"
            "[#9aa0a6]  /did               show your DID[/]\n"
            "[#9aa0a6]  /alias <name> <did> label a DID[/]\n"
            "[#9aa0a6]  /alias list        show aliases[/]\n"
            "[#9aa0a6]  /unalias <name>    remove[/]\n"
            "[#9aa0a6]  ctrl+r             refresh now[/]"
        )
        pop.add_class("visible")
        if self._help_timer:
            self._help_timer.stop()
        self._help_timer = self.set_timer(4.5, self._hide_help)

    def _hide_help(self):
        try:
            self.query_one("#help-pop").remove_class("visible")
        except Exception:
            pass
        self._help_timer = None

    def _position_help(self):
        pop = self.query_one("#help-pop")
        pop.styles.position = "absolute"
        w = 48
        try:
            x = max(0, self.size.width - w - 2)
        except Exception:
            x = 60
        pop.styles.offset = (x, 2)

    def _position_clock(self):
        clk = self.query_one("#live-clock")
        clk.styles.position = "absolute"
        clk.styles.offset = (0, 0)

    def _update_clock(self):
        try:
            t = time.strftime("%H:%M UTC", time.gmtime())
            self.query_one("#live-clock").update(
                f"[#6b6b75]{t}[/] · [#2ecc71]●[/] [#6b6b75]live[/]"
            )
        except Exception:
            pass

    def compose(self) -> ComposeResult:
        yield VerticalScroll(id="header")
        with Horizontal(id="main"):
            yield VerticalScroll(id="sidebar")
            yield VerticalScroll(id="feed")
        yield Static("", id="help-pop")
        yield Static("", id="live-clock")
        yield Input(
            placeholder="Type a message and press Enter to sign & send"
            if self.key else "Read-only — restart with --key identity.pem to post",
            id="input",
        )
        yield Horizontal(
            Static("", id="status-left"),
            Static("", id="status-right"),
            id="statusbar",
        )
        yield Static("↑↓ scroll · /join <room> · /alias <name> <did> · /did · ctrl+c quit", id="footer")

    async def on_mount(self):
        header = self.query_one("#header")
        header.border_title = f" FLOP MONITOR {VERSION} "
        self._position_help()
        self._position_clock()
        self._update_clock()
        # titles for boxed panels (like the screenshot: Library / Songs / etc)
        self.query_one("#sidebar").border_title = " Rooms "
        self.query_one("#feed").border_title = f" {self.room} "
        self.query_one("#input").border_title = " Message "
        banner_txt = Path(__file__).parent / "banner.txt"
        colors_file = Path(__file__).parent / "banner_colors.json"
        if banner_txt.exists():
            try:
                lines = banner_txt.read_text().splitlines()
                colors = (
                    json.loads(colors_file.read_text())
                    if colors_file.exists() else []
                )
                for row, line in enumerate(lines):
                    row_colors = colors[row] if row < len(colors) else []
                    header.mount(Static(banner_markup(line, row_colors),
                                        classes="banner"))
            except (OSError, json.JSONDecodeError):
                pass  # fall back to built-in title
        else:
            for row in render_pixel_title("FLOP MONITOR"):
                header.mount(Static(row, classes="banner"))
        ident = ("read-only" if not self.key else
                 self.my_did.replace("did:key:", "")[:8] + "…"
                 + self.my_did[-4:])
        header.mount(Static(SUBTITLE, classes="subtitle"))
        header.mount(Static(f"{AUTHOR}", classes="credit"))
        header.mount(Static(
            f"[{ACCENT}]●[/] [dim]{esc(self.room)} · {VERSION} · {ident}[/]",
            classes="banner-status"))
        feed = self.query_one("#feed")
        feed.mount(Static("Welcome back!", classes="welcome"))
        feed.mount(Static("What's new:", classes="whatsnew-head"))
        for item in (
            "Real-time room feed (polls every 5s)",
            "Messages signed with your Ed25519 identity",
            "/join <room> to switch · /did to show your DID",
        ):
            feed.mount(Static(f"[{ACCENT}]·[/]  {item}", classes="whatsnew"))
        feed.mount(Rule())
        self.query_one("#sidebar").styles.width = self.sidebar_width
        await self.update_sidebar()
        self.set_interval(5.0, self.poll)
        self.set_interval(1.0, self._update_clock)
        self.call_after_refresh(self.poll)
        self.query_one("#input").focus()

    def short(self, did: str) -> str:
        if self.my_did and did == self.my_did:
            return "you"
        if did in self.aliases:
            return self.aliases[did]
        d = did.replace("did:key:", "")
        return d[:8] + "…" + d[-4:]

    ALIASES_FILE = Path(__file__).parent / "did_aliases.json"

    def load_aliases(self):
        try:
            self.aliases = json.loads(self.ALIASES_FILE.read_text())
        except (OSError, json.JSONDecodeError):
            self.aliases = {}

    def save_aliases(self):
        try:
            self.ALIASES_FILE.write_text(json.dumps(self.aliases, indent=2))
        except OSError:
            pass

    ROOMS = ["lobby", "technocore", "general", "dev", "flop", "tips"]

    def update_status(self, state: str = "connected"):
        dot = "[green]●[/]" if state == "connected" else "[red]●[/]"
        right = f"{dot} {state}" + ("  ·  read-only" if not self.key else "")
        self.query_one("#status-left").update(
            f"{esc(self.room)} · seq {self.head_seq}"
        )
        self.query_one("#status-right").update(right)

    def _sidebar_rooms(self):
        rooms = list(self.ROOMS)
        if self.room not in rooms:
            rooms.append(self.room)
        return rooms

    async def update_sidebar(self):
        sb = self.query_one("#sidebar")
        await sb.remove_children()
        # title now lives in the box border, not as a row inside
        for i, r in enumerate(self._sidebar_rooms()):
            if r == self.room:
                label = f"[bold {ACCENT}]▸ {esc(r)}[/]"
            else:
                label = f"[dim]  {esc(r)}[/]"
            sb.mount(Static(label, classes="room-item", id=f"room-{i}"))

    def action_hide_help(self):
        self._hide_help()

    def on_resize(self, event: events.Resize) -> None:
        self._position_clock()
        if self.query_one("#help-pop").has_class("visible"):
            self._position_help()

    async def on_click(self, event: events.Click) -> None:
        # click anywhere hides the help popup (if open)
        if self.query_one("#help-pop").has_class("visible"):
            self._hide_help()
        wid = getattr(event.widget, "id", None) or ""
        if not wid.startswith("room-"):
            return
        try:
            room = self._sidebar_rooms()[int(wid[len("room-"):])]
        except (ValueError, IndexError):
            return
        if room != self.room:
            await self.switch_room(room)

    async def switch_room(self, room: str):
        self.room = room
        self.last_seq = None
        feed = self._feed()
        await feed.remove_children()
        feed.mount(Rule())
        # keep box title in sync with current room (like Songs header)
        try:
            self.query_one("#feed").border_title = f" {room} "
        except Exception:
            pass
        await self.update_sidebar()
        self.poll()

    def action_refresh(self):
        self.poll()

    def _feed(self):
        return self.query_one("#feed")

    def action_scroll_up(self):
        self._feed().scroll_up()

    def action_scroll_down(self):
        self._feed().scroll_down()

    def action_page_up(self):
        self._feed().scroll_page_up()

    def action_page_down(self):
        self._feed().scroll_page_down()

    def action_scroll_home(self):
        self._feed().scroll_home()

    def action_scroll_end(self):
        self._feed().scroll_end(animate=False)

    @work(exclusive=True)
    async def poll(self):
        try:
            q = (urllib.parse.urlencode({"format": "json", "limit": 30})
                 if self.last_seq is None else
                 urllib.parse.urlencode({"format": "json", "since": self.last_seq, "limit": 50}))
            data = await asyncio.to_thread(http_json, f"{BASE}/r/{urllib.parse.quote(self.room)}?{q}")
            msgs = sorted(data.get("messages", []), key=lambda m: m["seq"])
            if self.last_seq is None and msgs:
                msgs = msgs[-15:]
            feed = self.query_one("#feed")
            new = False
            for m in msgs:
                if self.last_seq is not None and m["seq"] <= self.last_seq:
                    continue
                ts = m.get("ts", "")[11:16]
                mine = self.my_did and m["from"] == self.my_did
                sender = self.short(m["from"])
                body = esc(m.get("text", ""))
                col = WHITE if mine else ACCENT
                wrap = Static("", classes="msg")
                wrap.update(
                    f"[bold {col}]● {esc(sender)}[/]  [dim]{ts}[/]\n"
                    f"  [{FG}]{body}[/]"
                )
                feed.mount(wrap)
                new = True
            if msgs:
                self.head_seq = max(m["seq"] for m in msgs)
                self.last_seq = max(m["seq"] for m in msgs)
            if new:
                feed.scroll_end(animate=False)
            self.update_status()
        except Exception as e:  # noqa: BLE001
            self.update_status(f"error: {str(e)[:40]}")

    @work(exclusive=True)
    async def _send(self, room: str, text: str):
        try:
            await asyncio.to_thread(post_message, room, text, self.key)
            self.poll()
        except Exception as e:  # noqa: BLE001
            self.notify(f"Send failed: {e}", severity="error")

    async def on_input_submitted(self, event: Input.Submitted):
        value = event.value.strip()
        event.input.value = ""
        if not value:
            return
        if value.startswith("/join "):
            room = value.split(None, 1)[1].strip()
            if room:
                await self.switch_room(room)
            return
        if value in ("/help", "?"):
            self._show_help()
            return
        if value == "/did":
            self.notify(self.my_did or "(read-only)", title="Your DID")
            return
        if value.startswith("/alias "):
            # /alias <name> <did>   or   /alias list
            parts = value.split()
            if len(parts) == 2 and parts[1] == "list":
                if self.aliases:
                    listing = "\n".join(f"{k} → {v[:20]}…{v[-6:]}" for k, v in self.aliases.items())
                    self.notify(listing, title="DID aliases")
                else:
                    self.notify("no aliases yet", title="DID aliases")
                return
            if len(parts) != 3:
                self.notify("usage: /alias <name> <did:key:...>\n       /alias list", severity="warning")
                return
            name, did = parts[1], parts[2]
            if not did.startswith("did:key:"):
                self.notify("DID must start with did:key:", severity="error")
                return
            self.aliases[did] = name
            self.save_aliases()
            self.poll()
            self.notify(f"{name} saved", title="Alias added")
            return
        if value.startswith("/unalias "):
            name = value.split(None, 1)[1].strip()
            matches = [d for d, n in self.aliases.items() if n == name]
            if matches:
                for d in matches:
                    del self.aliases[d]
                self.save_aliases()
                self.notify(f"{name} removed", title="Alias deleted")
            else:
                self.notify(f"no alias named {name}", severity="warning")
            return
        if not self.key:
            self.notify("Read-only mode — restart with --key identity.pem", severity="warning")
            return
        self._send(self.room, value)


def cmd_setup(args):
    """One-command onboarding: generate encrypted Ed25519 DID key."""
    import getpass
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives import serialization
    except ImportError:
        raise SystemExit("Missing dependency. Run: pip install -r requirements.txt")
    out = args.out
    if out.exists():
        if input(f"{out} already exists. Overwrite? [y/N] ").strip().lower() != "y":
            print("Aborted - existing key kept.")
            return
    while True:
        pw = getpass.getpass("Choose a passphrase (min 12 chars): ")
        if len(pw) < 12:
            print("Too short - 12+ characters.")
            continue
        pw2 = getpass.getpass("Repeat passphrase: ")
        if pw != pw2:
            print("Passphrases don't match, try again.")
            continue
        break
    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.BestAvailableEncryption(pw.encode()),
    )
    out.write_bytes(pem)
    out.chmod(0o600)
    did = did_from_key(key)
    print()
    print("DID key created:", out)
    print("Your DID:", did)
    print()
    print("Save this DID - it is your identity.")
    print("Start posting:")
    print(f"  python3 {Path(sys.argv[0]).name} --key {out}")


def main():
    ap = argparse.ArgumentParser(
        prog="technocore_tui.py",
        description="FLOP Monitor — signed chat terminal client for Technocore",
        epilog=(
            "examples:\n"
            "  %(prog)s                          read-only lobby, no key needed\n"
            "  %(prog)s --room dev               read-only, pick a room\n"
            "  %(prog)s setup                    create your DID key (one time)\n"
            "  %(prog)s --key identity.pem       full mode: sign & post"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = ap.add_subparsers(dest="command")
    p_setup = sub.add_parser("setup", help="generate your DID key (one-time)")
    p_setup.add_argument("--out", type=Path, default=Path("identity.pem"),
                         help="where to save the key (default: identity.pem)")
    ap.add_argument("--room", default="lobby", help="room to join (default: lobby)")
    ap.add_argument("--key", type=Path, default=None, metavar="FILE",
                    help="Ed25519 PEM key — enables signed posting")
    ap.add_argument("--sidebar-width", type=int, default=24,
                    metavar="N",
                    help="room sidebar width in columns (default 24)")
    args = ap.parse_args()

    if args.command == "setup":
        cmd_setup(args)
        return

    key = None
    if args.key:
        import getpass
        if load_pem_private_key is None:
            raise SystemExit("Missing dependency. Run: pip install -r requirements.txt")
        data = args.key.read_bytes()
        pw = getpass.getpass("Passphrase: ").encode()
        try:
            key = load_pem_private_key(data, password=pw)
        except ValueError:
            raise SystemExit("Wrong passphrase or corrupted key file.")

    TechnocoreTUI(args.room, key, sidebar_width=args.sidebar_width).run()


if __name__ == "__main__":
    main()
