import unittest
from ai_workflow.cli import _format_brief

class BriefFormatTests(unittest.TestCase):
    def test_json_markdown_prompt_formats(self):
        packet = {
            "task": "Add rate limiter",
            "lane": "full",
            "risk": "high",
            "model_tier": "capable",
            "execution_provider": "superpowers",
            "execution_hint": "Use subagent-driven-development",
            "budget": {"estimated_context_tokens": 6000, "max_output_tokens": 1200},
            "changed_files_detected": ["auth.py"],
            "context": [{"source": "source", "text": "def check_rate(): pass"}],
            "invariants": "no breaking change"
        }
        
        # JSON
        out_json = _format_brief(packet, "json")
        self.assertIn('"task": "Add rate limiter"', out_json)

        # Markdown
        out_md = _format_brief(packet, "markdown")
        self.assertIn("# Brief: Add rate limiter", out_md)
        self.assertIn("**Lane**: full", out_md)
        self.assertIn("def check_rate(): pass", out_md)

        # Prompt
        out_prompt = _format_brief(packet, "prompt")
        self.assertIn("[TASK] Add rate limiter", out_prompt)
        self.assertIn("[LANE] full [RISK] high", out_prompt)
        self.assertIn("[CONTEXT_START]", out_prompt)
        self.assertIn("def check_rate(): pass", out_prompt)
        self.assertIn("[INVARIANTS] no breaking change", out_prompt)
