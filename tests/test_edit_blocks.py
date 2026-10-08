import unittest

from agent.edit_blocks import (EditFormatError, apply_blocks, apply_edit_response,
                               feedback_for, parse_blocks)


def block(search, replace):
    return f"<<<<<<< SEARCH\n{search}\n=======\n{replace}\n>>>>>>> REPLACE\n"


FILE = 'ABBRS = {\n    "a",\n    "b",\n    "c",\n}\n\nTHRESHOLD = 3\n'


class ParseTests(unittest.TestCase):
    def test_single_block(self):
        blocks = parse_blocks(block('    "a",', '    "aa",'))
        self.assertEqual((blocks[0].search, blocks[0].replace), (['    "a",'], ['    "aa",']))

    def test_several_blocks_in_order(self):
        blocks = parse_blocks(block("x", "y") + block("p", "q"))
        self.assertEqual([b.search for b in blocks], [["x"], ["p"]])

    def test_text_and_fences_around_blocks_are_ignored(self):
        reply = "Here is the fix:\n```\n" + block("x", "y") + "```\nDone."
        self.assertEqual(len(parse_blocks(reply)), 1)

    def test_multiline_sections_and_empty_replacement(self):
        blocks = parse_blocks("<<<<<<< SEARCH\none\ntwo\n=======\n>>>>>>> REPLACE\n")
        self.assertEqual((blocks[0].search, blocks[0].replace), (["one", "two"], []))

    def test_no_blocks_is_an_error(self):
        with self.assertRaisesRegex(EditFormatError, "no SEARCH/REPLACE blocks"):
            parse_blocks("I changed the file, trust me.")

    def test_missing_divider(self):
        with self.assertRaisesRegex(EditFormatError, "divider"):
            parse_blocks("<<<<<<< SEARCH\nx\n")

    def test_missing_replace_line(self):
        with self.assertRaisesRegex(EditFormatError, "REPLACE"):
            parse_blocks("<<<<<<< SEARCH\nx\n=======\ny\n")

    def test_empty_search_is_rejected(self):
        with self.assertRaisesRegex(EditFormatError, "empty SEARCH"):
            parse_blocks("<<<<<<< SEARCH\n\n=======\ny\n>>>>>>> REPLACE\n")

    def test_whole_file_reply_is_not_accepted(self):
        with self.assertRaises(EditFormatError):
            parse_blocks(FILE)


class ApplyTests(unittest.TestCase):
    def test_exact_unique_match(self):
        result = apply_edit_response(FILE, block('    "b",', '    "b",\n    "bb",'))
        self.assertTrue(result.ok)
        self.assertEqual(result.content, FILE.replace('    "b",\n', '    "b",\n    "bb",\n'))

    def test_only_the_matched_lines_change(self):
        result = apply_edit_response(FILE, block("THRESHOLD = 3", "THRESHOLD = 4"))
        self.assertEqual(result.content, FILE.replace("THRESHOLD = 3", "THRESHOLD = 4"))

    def test_not_found_reports_and_leaves_no_content(self):
        result = apply_edit_response(FILE, block('    "zz",', "x"))
        self.assertFalse(result.ok)
        self.assertIsNone(result.content)
        self.assertIn("were not found", result.errors[0])

    def test_ambiguous_match_asks_for_more_context(self):
        text = "x = 1\ny = 2\nx = 1\n"
        result = apply_edit_response(text, block("x = 1", "x = 9"))
        self.assertFalse(result.ok)
        self.assertIn("match 2 places", result.errors[0])
        self.assertIn("more unchanged lines", result.errors[0])

    def test_extra_context_makes_an_ambiguous_match_unique(self):
        text = "x = 1\ny = 2\nx = 1\nz = 3\n"
        result = apply_edit_response(text, block("x = 1\nz = 3", "x = 9\nz = 3"))
        self.assertEqual(result.content, "x = 1\ny = 2\nx = 9\nz = 3\n")

    def test_trailing_whitespace_difference_still_matches(self):
        text = "alpha   \nbeta\t\ngamma\n"
        result = apply_edit_response(text, block("alpha\nbeta", "ALPHA\nBETA"))
        self.assertEqual(result.content, "ALPHA\nBETA\ngamma\n")

    def test_leading_indentation_must_match(self):
        result = apply_edit_response("def f():\n    return 1\n", block("return 1", "return 2"))
        self.assertFalse(result.ok)

    def test_failed_search_hint_shows_the_real_lines(self):
        text = 'a = 1\nvalues = [\n    "one",\n    "two",\n]\n'
        result = apply_edit_response(text, block('values = [\n    "uno",', "x"))
        self.assertIn("first line of your SEARCH block does appear at line 2", result.errors[0])
        self.assertIn('    "one",', result.errors[0])

    def test_blocks_apply_in_order_and_can_build_on_each_other(self):
        reply = block("THRESHOLD = 3", "THRESHOLD = 4") + block("THRESHOLD = 4", "THRESHOLD = 5")
        self.assertIn("THRESHOLD = 5", apply_edit_response(FILE, reply).content)

    def test_all_or_nothing_when_a_later_block_fails(self):
        reply = block("THRESHOLD = 3", "THRESHOLD = 4") + block("nope", "x")
        result = apply_edit_response(FILE, reply)
        self.assertIsNone(result.content)
        self.assertEqual(len(result.errors), 1)
        self.assertTrue(result.errors[0].startswith("block 2"))

    def test_every_failed_block_is_reported(self):
        result = apply_edit_response(FILE, block("nope1", "x") + block("nope2", "y"))
        self.assertEqual(len(result.errors), 2)

    def test_edit_that_changes_nothing_is_reported(self):
        result = apply_edit_response(FILE, block("THRESHOLD = 3", "THRESHOLD = 3"))
        self.assertFalse(result.ok)
        self.assertIn("did not change the file", result.errors[0])

    def test_deleting_lines_with_an_empty_replacement(self):
        result = apply_edit_response("a\nb\nc\n", "<<<<<<< SEARCH\nb\n=======\n>>>>>>> REPLACE\n")
        self.assertEqual(result.content, "a\nc\n")

    def test_format_errors_never_raise_from_apply_edit_response(self):
        result = apply_edit_response(FILE, "not a block")
        self.assertFalse(result.ok)
        self.assertIn("no SEARCH/REPLACE blocks", result.errors[0])


class ByteFidelityTests(unittest.TestCase):
    """The reason this format exists: lines the model was not asked to touch stay identical."""

    def test_non_ascii_characters_elsewhere_survive(self):
        # yasbd regression: a whole-file rewrite turned the Myanmar full stop into a duplicate
        text = ('DOT_LIKE_PATTERN = r"[.．။।॥·]"\n'
                'ENDERS = ["!", "။", "።"]\n'
                'ABBRS = {"vs"}\n')
        result = apply_edit_response(text, block('ABBRS = {"vs"}', 'ABBRS = {"vs", "v.s."}'))
        self.assertEqual(result.content, text.replace('{"vs"}', '{"vs", "v.s."}'))
        self.assertIn("။", result.content.splitlines()[0])

    def test_crlf_file_stays_crlf(self):
        text = "a = 1\r\nb = 2\r\nc = 3\r\n"
        result = apply_edit_response(text, block("b = 2", "b = 22\nb2 = 5"))
        self.assertEqual(result.content, "a = 1\r\nb = 22\r\nb2 = 5\r\nc = 3\r\n")

    def test_missing_final_newline_stays_missing(self):
        result = apply_edit_response("a = 1\nb = 2", block("b = 2", "b = 3"))
        self.assertEqual(result.content, "a = 1\nb = 3")

    def test_final_newline_stays_present(self):
        result = apply_edit_response("a = 1\nb = 2\n", block("b = 2", "b = 3"))
        self.assertEqual(result.content, "a = 1\nb = 3\n")

    def test_form_feed_and_other_unicode_separators_are_not_treated_as_lines(self):
        text = "a = 1\n# page\x0cbreak x\nb = 2\n"
        result = apply_edit_response(text, block("b = 2", "b = 3"))
        self.assertEqual(result.content, text.replace("b = 2", "b = 3"))


class FeedbackTests(unittest.TestCase):
    def test_feedback_contains_the_problem_and_the_previous_reply(self):
        text = feedback_for("my bad reply", ["block 1: the SEARCH lines were not found"])
        self.assertIn("block 1: the SEARCH lines were not found", text)
        self.assertIn("my bad reply", text)
        self.assertIn("corrected SEARCH/REPLACE blocks", text)


if __name__ == "__main__":
    unittest.main()
