"""Bar renderer tests. The canonical case is disler's own documented output."""
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from bar import render, CELLS


class TestBar(unittest.TestCase):
    def test_disler_canonical_example(self):
        """The exact string in context-bar.ts's docstring: [###~====-!-|--------] 40%"""
        self.assertEqual(render(40, 15, 20, 50, 60).text, "[###~====-!-|--------] 40%")

    def test_unknown_usage_renders_empty_frame(self):
        out = render(None)
        self.assertEqual(out.label, "--%")
        self.assertEqual(out.bar, "-" * CELLS)

    def test_cached_share_never_exceeds_used(self):
        self.assertNotIn("#", render(10, 90).bar[2:])

    def test_stronger_marker_wins_the_same_cell(self):
        """Zero buffer puts warning and forced in one cell; forced must win."""
        bar = render(0, 0, 50, 50, 50).bar
        self.assertEqual(bar.count("|"), 1)
        self.assertNotIn("!", bar)

    def test_full_and_empty(self):
        self.assertEqual(render(100).bar, "=" * CELLS)
        self.assertEqual(render(0).bar, "-" * CELLS)

    def test_always_twenty_cells(self):
        for pct in (None, 0, 0.1, 37.5, 99.9, 100, 150):
            self.assertEqual(len(render(pct, 10, 60, 75, 85).bar), CELLS, pct)

    def test_offscale_markers_are_dropped(self):
        self.assertNotIn("~", render(50, 0, 150, None, None).bar)


if __name__ == "__main__":
    unittest.main()
