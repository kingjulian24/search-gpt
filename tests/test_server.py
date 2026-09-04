"""Unit and integration tests for search-gpt."""

import asyncio
import re
import unittest
from pathlib import Path
from src.indexer import DEFAULT_DB_PATH
from src.server import (
    get_archive_stats,
    search_conversations,
    get_conversation,
    list_conversations,
    extract_nuggets,
    server,
)


class TestSearchGPT(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert DEFAULT_DB_PATH.exists(), "conversations.db must exist before running tests"

    def test_get_archive_stats(self):
        stats = get_archive_stats()
        self.assertIn("**Total Conversations:**", stats)
        self.assertIn("**Total Messages:**", stats)
        self.assertIn("User Messages (Prompts)", stats)
        self.assertIn("Assistant Responses", stats)

    def test_search_conversations(self):
        result = search_conversations("quadratic equation")
        self.assertIn("Search Results", result)
        self.assertIn("quadratic", result.lower())

    def test_search_prefix(self):
        result = search_conversations("pyth*")
        self.assertIn("Search Results", result)
        self.assertIn("python", result.lower())

    def test_search_special_characters_no_crash(self):
        # Queries with special chars should not crash FTS5
        res1 = search_conversations("***")
        self.assertIn("valid search query", res1.lower())

        res2 = search_conversations("c++")
        self.assertNotIn("operationalerror", res2.lower())

        res3 = search_conversations('"unclosed quote')
        self.assertNotIn("operationalerror", res3.lower())

    def test_search_deduplication(self):
        # Broad keyword that appears many times in single conversations
        result = search_conversations("python", limit=5, dedup_conversations=True)
        # Extract all conversation IDs from output
        conv_ids = re.findall(r"Conversation ID:\s*`([a-f0-9\-]+)`", result)
        self.assertEqual(len(conv_ids), len(set(conv_ids)), "All returned conversation IDs should be distinct")

    def test_search_with_role_filter(self):
        result_user = search_conversations("quadratic", role_filter="user")
        self.assertIn("🧑 User", result_user)
        self.assertNotIn("🤖 Assistant", result_user)

    def test_list_conversations(self):
        result = list_conversations(limit=5)
        self.assertIn("Conversation Archive", result)
        self.assertIn("ID:", result)

    def test_list_conversations_filter(self):
        result = list_conversations(query="Voice")
        self.assertIn("Voice", result)

    def test_extract_nuggets(self):
        result = extract_nuggets("quadratic equation")
        self.assertIn("💡 Nugget:", result)
        self.assertIn("Core Insight", result)

    def test_get_conversation_valid(self):
        # List to get an ID
        first_list = list_conversations(limit=1)
        match = re.search(r"ID: `([a-f0-9\-]+)`", first_list)
        self.assertIsNotNone(match, "Should extract conversation ID")
        conv_id = match.group(1)

        transcript = get_conversation(conv_id, max_messages=5)
        self.assertIn("Conversation ID:", transcript)
        self.assertIn("Turn 0", transcript)

    def test_get_conversation_invalid(self):
        transcript = get_conversation("non-existent-uuid-1234")
        self.assertIn("Conversation not found", transcript)

    def test_mcp_tools_registered(self):
        tools = [t.name for t in asyncio.run(server.list_tools())]
        expected = ["search_conversations", "get_conversation", "list_conversations", "extract_nuggets", "get_archive_stats"]
        for exp in expected:
            self.assertIn(exp, tools)


if __name__ == "__main__":
    unittest.main()
