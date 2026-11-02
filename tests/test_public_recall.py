from pathlib import Path
import tempfile
import unittest
from companion_memory import CompanionMemory


class TokenRecallTests(unittest.TestCase):
    def test_greeting_does_not_match_scheduler_substrings(self):
        with tempfile.TemporaryDirectory() as folder:
            memory=CompanionMemory(Path(folder)/'memory')
            memory.remember('Implement recall_for_scheduler with scheduler helpers')
            self.assertEqual(memory.recall_for_scheduler('hello'),[])

    def test_english_acronym_is_still_recalled(self):
        with tempfile.TemporaryDirectory() as folder:
            memory=CompanionMemory(Path(folder)/'memory')
            mid=memory.remember('Use MCP to inspect a local service')
            self.assertIn(mid,[row['id'] for row in memory.recall_for_scheduler('mcp')])
