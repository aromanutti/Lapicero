"""Ask Claude conversations saved per page: one JSON file per chat in a folder beside the library."""

import json
import os
from pathlib import Path
import tempfile
import time
from uuid import uuid4

CHATS_DIR = "chats"


def new_chat(page_id):
    """A chat started on page_id (None when no page was open)."""
    now = time.time()
    return {"id": uuid4().hex[:12], "page_id": page_id, "session_id": None,
            "created": now, "updated": now, "entries": []}


def chat_title(chat, length=48):
    """The chat's first question on one line, shortened."""
    question = " ".join(chat["entries"][0]["question"].split()) if chat["entries"] else ""
    return question if len(question) <= length else question[:length - 1].rstrip() + "…"


class ChatStore:
    """Chats in memory, each written to <folder>/<id>.json on save. folder None keeps them in memory only."""

    def __init__(self, folder):
        self.folder = Path(folder) if folder is not None else None
        self.chats = {}
        self.load_errors = []
        if self.folder is not None and self.folder.is_dir():
            for path in self.folder.glob("*.json"):
                try:
                    chat = json.loads(path.read_text(encoding="utf-8"))
                    if not isinstance(chat, dict) or not isinstance(chat.get("entries"), list) or \
                            chat.get("id") != path.stem:
                        raise ValueError("not a chat")
                    self.chats[chat["id"]] = chat
                except (OSError, ValueError) as exc:  # A damaged chat must not break the others.
                    self.load_errors.append(f"{path.name}: {exc}")

    def for_page(self, page_id):
        """Chats started on page_id that have at least one question, newest first."""
        chats = [chat for chat in self.chats.values() if chat.get("page_id") == page_id and chat["entries"]]
        return sorted(chats, key=lambda chat: chat.get("updated", 0), reverse=True)

    def save(self, chat):
        chat["updated"] = time.time()
        self.chats[chat["id"]] = chat
        if self.folder is None:
            return
        self.folder.mkdir(parents=True, exist_ok=True)
        target = self.folder / f"{chat['id']}.json"
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.folder,
                                             prefix=f".{target.name}.", suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(chat, stream, ensure_ascii=False)
            os.replace(temporary, target)
            temporary = None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
