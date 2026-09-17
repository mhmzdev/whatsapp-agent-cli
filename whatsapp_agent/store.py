"""What was said, keyed by the platform's own message id.

One JSON object per line: `{"id", "dir", "ts", "text"}` — the record shape
hisab-whatsapp already writes, so both can read the same file. It exists for two
reasons that arrive in different tickets: `recv` skips an id it has already
delivered (#5), and a caller resolving a quoted reply needs the text of the
message that was quoted.

The store lives in the state directory, which is never the caller's working
directory, so a program reading a project folder cannot read this.
"""

import json
import os
import time
from pathlib import Path

KEEP_DAYS = 30
MESSAGES = "messages.jsonl"
CREATOR = "creator"


class Store:
    def __init__(self, state_dir, keep_days=KEEP_DAYS, now=time.time):
        self.dir = Path(state_dir)
        self.path = self.dir / MESSAGES
        self.keep_days = keep_days
        self._now = now

    # ---------------------------------------------------------------- messages
    def add(self, msg_id, direction, text=""):
        """Append one record. Returns the id, so a caller can chain."""
        if direction not in ("in", "out"):
            raise ValueError(f"direction must be 'in' or 'out', not {direction!r}")
        record = {"id": msg_id, "dir": direction, "ts": int(self._now()), "text": text}
        self.dir.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        return msg_id

    def all(self):
        """Every record, oldest first. A corrupt line is skipped, not fatal: this
        is an append-only log a crash can truncate mid-write."""
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out

    def lookup(self, msg_id):
        """The text of a stored message, or None. The last write wins."""
        found = None
        for record in self.all():
            if record.get("id") == msg_id:
                found = record.get("text")
        return found

    def seen(self, msg_id):
        return any(record.get("id") == msg_id for record in self.all())

    def prune(self):
        """Drop records older than keep_days. Returns how many were dropped."""
        records = self.all()
        if not records:
            return 0
        cutoff = self._now() - self.keep_days * 86400
        kept = [r for r in records if r.get("ts", 0) >= cutoff]
        if len(kept) == len(records):
            return 0
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".jsonl.tmp")
        tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in kept), encoding="utf-8")
        os.replace(tmp, self.path)
        return len(records) - len(kept)

    # ---------------------------------------------------------------- creator
    def creator(self):
        """The id an agent may message, learned from an inbound message. None until
        `recv` has run at least once (#5); `send` asks for `--to` until then."""
        path = self.dir / CREATOR
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8").strip() or None

    def set_creator(self, user_id):
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / CREATOR).write_text(str(user_id).strip(), encoding="utf-8")
        return user_id
