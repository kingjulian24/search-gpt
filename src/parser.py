"""Parser for ChatGPT export JSON files."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, List, Optional


@dataclass
class ParsedMessage:
    id: str
    conversation_id: str
    turn_index: int
    role: str
    content: str
    create_time: Optional[float] = None

    @property
    def iso_date(self) -> str:
        if self.create_time:
            try:
                dt = datetime.fromtimestamp(self.create_time, tz=timezone.utc)
                return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
            except (ValueError, OSError):
                pass
        return "Unknown Date"


@dataclass
class ParsedConversation:
    id: str
    title: str
    create_time: Optional[float]
    update_time: Optional[float]
    model: str
    source_file: str
    messages: List[ParsedMessage] = field(default_factory=list)

    @property
    def iso_create_date(self) -> str:
        if self.create_time:
            try:
                dt = datetime.fromtimestamp(self.create_time, tz=timezone.utc)
                return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
            except (ValueError, OSError):
                pass
        return "Unknown Date"

    @property
    def message_count(self) -> int:
        return len(self.messages)


def extract_text_from_content(content: dict[str, Any]) -> str:
    """Extract string text from message content parts safely."""
    if not isinstance(content, dict):
        return ""
    
    parts = content.get("parts", [])
    if not parts:
        text = content.get("text")
        return str(text).strip() if text else ""

    text_pieces = []
    for part in parts:
        if isinstance(part, str):
            if part.strip():
                text_pieces.append(part)
        elif isinstance(part, dict):
            # Sometimes parts can be structured (e.g. image_url, code block, etc.)
            if "text" in part and isinstance(part["text"], str):
                text_pieces.append(part["text"])
            elif "image_url" in part:
                text_pieces.append("[Image Attachment]")
    return "\n\n".join(text_pieces).strip()


def parse_conversation_dict(
    conv_data: dict[str, Any],
    source_file: str = ""
) -> Optional[ParsedConversation]:
    """Parse a single conversation dictionary into a ParsedConversation."""
    conv_id = conv_data.get("id") or conv_data.get("conversation_id")
    if not conv_id:
        return None

    title = (conv_data.get("title") or "Untitled Conversation").strip()
    create_time = conv_data.get("create_time")
    update_time = conv_data.get("update_time")
    model = conv_data.get("default_model_slug") or ""
    mapping = conv_data.get("mapping", {})

    if not isinstance(mapping, dict):
        return None

    current_node_id = conv_data.get("current_node")
    linear_nodes: List[dict[str, Any]] = []

    if current_node_id and current_node_id in mapping:
        # Trace current_node back to root via parent links
        curr: Optional[str] = current_node_id
        visited: set[str] = set()
        while curr and curr in mapping and curr not in visited:
            visited.add(curr)
            node = mapping[curr]
            linear_nodes.append(node)
            curr = node.get("parent")
        linear_nodes.reverse()
    else:
        # Fallback: order by create_time if current_node path unavailable
        all_nodes = [
            n for n in mapping.values()
            if isinstance(n, dict) and n.get("message")
        ]
        all_nodes.sort(
            key=lambda n: (n.get("message", {}).get("create_time") or 0.0)
        )
        linear_nodes = all_nodes

    messages: List[ParsedMessage] = []
    turn_index = 0

    for node in linear_nodes:
        msg = node.get("message")
        if not msg or not isinstance(msg, dict):
            continue

        author = msg.get("author", {})
        role = author.get("role") if isinstance(author, dict) else "unknown"
        content_dict = msg.get("content", {})
        text = extract_text_from_content(content_dict)

        # Skip empty system or metadata messages without substantive text
        if not text and role in ("system", "tool"):
            continue

        msg_id = msg.get("id") or node.get("id") or f"{conv_id}_{turn_index}"
        msg_time = msg.get("create_time") or create_time

        messages.append(
            ParsedMessage(
                id=str(msg_id),
                conversation_id=str(conv_id),
                turn_index=turn_index,
                role=str(role),
                content=text,
                create_time=float(msg_time) if msg_time is not None else None,
            )
        )
        turn_index += 1

    return ParsedConversation(
        id=str(conv_id),
        title=title,
        create_time=float(create_time) if create_time is not None else None,
        update_time=float(update_time) if update_time is not None else None,
        model=str(model),
        source_file=source_file,
        messages=messages,
    )


def load_conversations_from_file(file_path: Path | str) -> Iterator[ParsedConversation]:
    """Stream and yield ParsedConversation objects from a JSON export file."""
    path = Path(file_path)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                parsed = parse_conversation_dict(item, source_file=path.name)
                if parsed:
                    yield parsed
    elif isinstance(data, dict):
        parsed = parse_conversation_dict(data, source_file=path.name)
        if parsed:
            yield parsed
