#!/usr/bin/env python3
"""Technocore TUI v3 — Claude Code style with FLOP banner.

Layout: FLOP pixel banner, welcome, what's new, chat-style feed,
bare prompt input, status bar. English UI.
"""
from __future__ import annotations

import argparse
import base64
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Input, Static

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
    req = urllib.request.Request(url, headers={"User-Agent": "tc-tui/3.0"})
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
        headers={"Content-Type": "application/json", "User-Agent": "tc-tui/3.0"},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        resp = json.load(r)
    posted = resp.get("posted") or {}
    if posted.get("text") != " ".join(text.split()):
        raise RuntimeError("server response mismatch")
    return posted


def esc(s: str) -> str:
    return s.replace("[", "\\[")


class TechnocoreTUI(App):
    CSS = f"""
    Screen {{ background: {BG}; }}
    .roombar {{
        height: 1; padding: 0 3; background: {BG}; text-align: right;
    }}
    #feed {{
        height: 1fr; padding: 0 3; background: {BG};
        scrollbar-size: 0 0;
    }}
    #header {{
        height: auto; max-height: 12; padding: 0 3; background: {BG};
        scrollbar-size: 0 0;
    }}
    .banner {{ color: {WHITE}; margin-bottom: 1; }}
    .welcome {{ color: {WHITE}; text-style: bold; margin-bottom: 1; }}
    .whatsnew {{ color: {DIM}; margin-bottom: 0; }}
    .whatsnew-head {{ color: {DIM}; text-style: bold; }}
    .sep {{ color: {DIM}; margin-top: 1; margin-bottom: 1; }}
    .msg {{ margin-bottom: 1; }}
    .msg-user {{ color: {WHITE}; margin-bottom: 1; }}
    .sender {{ color: {ACCENT}; text-style: bold; }}
    .time {{ color: {DIM}; }}
    .body {{ color: {FG}; }}
    .mine .sender {{ color: {ACCENT}; }}
    #input {{
        dock: bottom; height: 3; padding: 0 2; background: {BG}; border: none;
    }}
    #input > .input--placeholder {{ color: {DIM}; }}
    #status {{
        dock: bottom; height: 1; color: {DIM}; padding: 0 3;
    }}
    """
    BINDINGS = [
        ("ctrl+c", "quit", "Quit"),
        ("ctrl+r", "refresh", "Refresh"),
        ("up", "scroll_up", "Scroll up"),
        ("down", "scroll_down", "Scroll down"),
        ("pageup", "page_up", "Page up"),
        ("pagedown", "page_down", "Page down"),
        ("home", "scroll_home", "Top"),
        ("end", "scroll_end", "Bottom"),
    ]

    def __init__(self, room: str, key=None):
        super().__init__()
        self.room = room
        self.key = key
        self.last_seq = None
        self.my_did = did_from_key(key) if key else None
        self.head_seq = 0
        self.load_aliases()

    def compose(self) -> ComposeResult:
        yield VerticalScroll(id="header")
        yield VerticalScroll(id="feed")
        yield Input(
            placeholder="Type a message and press Enter to sign & send"
            if self.key else "Read-only — restart with --key identity.pem to post",
            id="input",
        )
        yield Static("", id="status")

    def on_mount(self):
        header = self.query_one("#header")
        banner_txt = Path(__file__).parent / "banner.txt"
        colors = json.loads((Path(__file__).parent / "banner_colors.json").read_text())
        if banner_txt.exists():
            for row, line in enumerate(banner_txt.read_text().splitlines()):
                row_colors = colors[row] if row < len(colors) else []
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
                header.mount(Static("".join(parts), classes="banner"))
        # room tabs overlay: absolutely positioned top-right, beside the logo
        from textual.containers import Horizontal
        bar = Static("", id="roombar", classes="roombar")
        bar.styles.position = "absolute"
        bar.styles.top = 2
        bar.styles.right = 1
        self.mount(bar)
        feed = self.query_one("#feed")
        feed.mount(Static("Welcome back!", classes="welcome"))
        feed.mount(Static("What's new:", classes="whatsnew-head"))
        for item in (
            "· Real-time room feed (polls every 5s)",
            "· Messages signed with your Ed25519 identity",
            "· /join <room> to switch · /did to show your DID",
        ):
            w = Static(item, classes="whatsnew")
            w.markup = False
            feed.mount(w)
        sep = Static("─" * 200, classes="sep")
        feed.mount(sep)
        self.set_interval(5.0, self.poll)
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
        self.ALIASES_FILE.write_text(json.dumps(self.aliases, indent=2))

    ROOMS = ["lobby", "technocore", "general", "dev", "flop", "tips"]

    def update_roombar(self):
        parts = []
        for r in self.ROOMS:
            if r == self.room:
                parts.append(f"[bold {ACCENT}][{r}][/]".replace(f"[{r}]", f"\\[{r}]"))
            else:
                parts.append(f"[dim]{r}[/]")
        self.query_one("#roombar").update("  ".join(parts))

    def update_status(self, state: str = "connected"):
        dot = "[green]●[/]" if state == "connected" else "[red]●[/]"
        self.query_one("#status").update(
            f" {self.room}  ·  seq {self.head_seq}  ·  {dot} {state}"
            + ("  ·  read-only" if not self.key else "")
        )

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

    def poll(self):
        try:
            q = (urllib.parse.urlencode({"format": "json", "limit": 30})
                 if self.last_seq is None else
                 urllib.parse.urlencode({"format": "json", "since": self.last_seq, "limit": 50}))
            data = http_json(f"{BASE}/r/{urllib.parse.quote(self.room)}?{q}")
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
                wrap = Static("", classes="msg me" if mine else "msg")
                wrap.update(
                    f"[{ACCENT}]●[/] [bold {ACCENT}]{sender}[/] [dim]{ts}[/]\n"
                    f"[{FG}]{body}[/]"
                )
                feed.mount(wrap)
                new = True
            if msgs:
                self.head_seq = max(m["seq"] for m in msgs)
                self.last_seq = max(m["seq"] for m in msgs)
            if new:
                feed.scroll_end(animate=False)
            self.update_status()
            self.update_roombar()
        except Exception as e:  # noqa: BLE001
            self.update_status(f"error: {str(e)[:40]}")

    def on_input_submitted(self, event: Input.Submitted):
        value = event.value.strip()
        event.input.value = ""
        if not value:
            return
        if value.startswith("/join "):
            self.room = value.split(None, 1)[1].strip()
            self.last_seq = None
            feed = self.query_one("#feed")
            feed.remove_children()
            sep = Static("─" * 200, classes="sep")
            feed.mount(sep)
            self.update_roombar()
            self.poll()
            return
        if value in ("/help", "?"):
            self.notify("/join <room>  switch room\n/did  show your DID\n/alias <name> <did>  label a DID\n/alias list  show aliases\n/unalias <name>  remove\nctrl+r  refresh now",
                        title="Commands")
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
        try:
            post_message(self.room, value, self.key)
            self.poll()
        except Exception as e:  # noqa: BLE001
            self.notify(f"Send failed: {e}", severity="error")


def main():
    ap = argparse.ArgumentParser(description="Technocore terminal UI")
    ap.add_argument("--room", default="lobby")
    ap.add_argument("--key", type=Path, default=None)
    args = ap.parse_args()

    key = None
    if args.key:
        import getpass
        if load_pem_private_key is None:
            raise SystemExit("pip install cryptography")
        data = args.key.read_bytes()
        pw = getpass.getpass("Passphrase: ").encode()
        key = load_pem_private_key(data, password=pw)

    TechnocoreTUI(args.room, key).run()


if __name__ == "__main__":
    main()
