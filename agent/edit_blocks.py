"""
SEARCH/REPLACE edit blocks: the format the model uses to change a file.

Instead of rewriting a whole file (where a small model drops lines or mangles non-ASCII
characters it was never asked to touch), the model returns only the lines to change:

    <<<<<<< SEARCH
    exact lines currently in the file
    =======
    the lines that should replace them
    >>>>>>> REPLACE

Apply policy:
  - A SEARCH block must match exactly one place in the file, line for line.
  - Exact match first, then a whitespace-normalised match (trailing spaces, line endings).
  - Zero or several matches is a failure that is reported back to the model.
  - All blocks apply or none do: a failed reply never leaves a half-edited file.
  - Everything outside the matched lines is left byte-for-byte unchanged.
"""

import re
from dataclasses import dataclass, field

SEARCH_MARKER = re.compile(r"^<{5,9} SEARCH\s*$")
DIVIDER_MARKER = re.compile(r"^={5,9}\s*$")
REPLACE_MARKER = re.compile(r"^>{5,9} REPLACE\s*$")

# How many lines of the file to show the model when its first SEARCH line is found
# but the lines after it differ
HINT_CONTEXT_LINES = 6

EDIT_FORMAT_INSTRUCTIONS = """\
Return your changes as SEARCH/REPLACE blocks. Do NOT return the whole file.

Each block has this exact shape:

<<<<<<< SEARCH
(lines copied EXACTLY from the current file, including indentation)
=======
(the lines that should replace them)
>>>>>>> REPLACE

Rules:
- Copy the SEARCH lines character for character from the file shown. Do not retype
  from memory, and do not change quotes, spacing or non-ASCII characters.
- Each SEARCH block must match exactly ONE place in the file. If the lines you want
  also appear elsewhere, include a few unchanged lines around them to make it unique.
- Keep each block small: only the lines that change, plus the context needed to find them.
- Use several blocks for several separate changes. Blocks apply in order.
- Do not include any text outside the blocks, and do not add markdown fences.

Example. To add "v.s." after "vs." in a set:

<<<<<<< SEARCH
    "vs.",
    "viz.",
=======
    "vs.",
    "v.s.",
    "viz.",
>>>>>>> REPLACE
"""


@dataclass
class Block:
    search: list
    replace: list


@dataclass
class EditResult:
    """`content` is the edited file text, or None when the edits could not be applied."""
    content: str = None
    errors: list = field(default_factory=list)

    @property
    def ok(self):
        return self.content is not None


class EditFormatError(Exception):
    """The model's reply does not follow the SEARCH/REPLACE format."""


# ---------- parsing ----------

def parse_blocks(text):
    """
    Extracts the SEARCH/REPLACE blocks from a model reply.
    Text outside the blocks (explanations, markdown fences) is ignored.
    Raises EditFormatError for a missing, empty or unfinished block.
    """
    blocks = []
    state = "outside"
    search, replace = [], []

    for number, line in enumerate((text or "").splitlines(), start=1):
        if state == "outside":
            if SEARCH_MARKER.match(line):
                state, search, replace = "search", [], []
        elif state == "search":
            if DIVIDER_MARKER.match(line):
                state = "replace"
            elif SEARCH_MARKER.match(line):
                raise EditFormatError(f"line {number}: a new SEARCH started before the "
                                      "previous block's ======= divider")
            else:
                search.append(line)
        else:  # replace
            if REPLACE_MARKER.match(line):
                if not any(part.strip() for part in search):
                    raise EditFormatError(
                        f"block {len(blocks) + 1} has an empty SEARCH section; it must "
                        "contain the existing lines to replace")
                blocks.append(Block(search, replace))
                state = "outside"
            elif SEARCH_MARKER.match(line):
                raise EditFormatError(f"line {number}: a new SEARCH started before the "
                                      "previous block's >>>>>>> REPLACE")
            else:
                replace.append(line)

    if state != "outside":
        raise EditFormatError(f"block {len(blocks) + 1} is not finished: missing "
                              + ("the ======= divider" if state == "search"
                                 else "the >>>>>>> REPLACE line"))
    if not blocks:
        raise EditFormatError("no SEARCH/REPLACE blocks found in the reply")
    return blocks


# ---------- matching ----------

def _normalise(line):
    return line.rstrip()  # drops trailing spaces, tabs and a stray \r


def _find_matches(lines, search, key):
    """Start indexes where `search` occurs in `lines`, comparing key(line) line for line."""
    wanted = [key(line) for line in search]
    size = len(wanted)
    if size == 0 or size > len(lines):
        return []
    keyed = [key(line) for line in lines]
    return [i for i in range(len(lines) - size + 1) if keyed[i:i + size] == wanted]


def _hint(lines, search):
    """If the first SEARCH line exists somewhere, show the model the real lines there."""
    first = _normalise(search[0]).strip()
    if not first:
        return ""
    for i, line in enumerate(lines):
        if _normalise(line).strip() == first:
            shown = lines[i:i + max(len(search), HINT_CONTEXT_LINES)]
            return ("\nThe first line of your SEARCH block does appear at line "
                    f"{i + 1}, but the lines after it differ. The file actually has:\n"
                    + "\n".join(shown))
    return ""


def _locate(lines, search, number):
    """Returns (start_index, None) for exactly one match, else (None, error message)."""
    for key in (lambda line: line, _normalise):
        matches = _find_matches(lines, search, key)
        if len(matches) == 1:
            return matches[0], None
        if len(matches) > 1:
            where = ", ".join(str(i + 1) for i in matches[:5])
            return None, (f"block {number}: the SEARCH lines match {len(matches)} places "
                          f"(starting at lines {where}). Include more unchanged lines "
                          "around them so they match exactly one place.")
    return None, (f"block {number}: the SEARCH lines were not found in the file."
                  + _hint(lines, search))


# ---------- applying ----------

_LINE = re.compile(r"[^\n]*\n|[^\n]+")


def _split_lines(content):
    """
    [(text, ending)] per line, keeping each line's own ending ("\n", "\r\n" or "" for a
    last line without one), so lines we do not touch are written back unchanged.
    Splits only on \n, never on other Unicode line boundaries such as form feeds.
    """
    entries = []
    for raw in _LINE.findall(content):
        if raw.endswith("\r\n"):
            entries.append((raw[:-2], "\r\n"))
        elif raw.endswith("\n"):
            entries.append((raw[:-1], "\n"))
        else:
            entries.append((raw, ""))
    return entries


def apply_blocks(content, blocks):
    """
    Applies the blocks in order. Returns an EditResult: the new text if every block
    applied, otherwise no content and one error message per failed block.
    Lines outside the matched regions are returned byte-for-byte unchanged.
    """
    entries = _split_lines(content)
    file_eol = "\r\n" if any(ending == "\r\n" for _, ending in entries) else "\n"
    errors = []

    for number, block in enumerate(blocks, start=1):
        texts = [text for text, _ in entries]
        start, error = _locate(texts, block.search, number)
        if error:
            errors.append(error)
            continue  # keep checking later blocks so one reply reports every problem

        region = entries[start:start + len(block.search)]
        line_eol = region[0][1] or file_eol
        replacement = []
        for i, line in enumerate(block.replace):
            is_last = i == len(block.replace) - 1
            # the last line keeps the region's final ending, so a missing final newline stays missing
            replacement.append((line.rstrip("\r"), region[-1][1] if is_last else line_eol))
        entries[start:start + len(block.search)] = replacement

    if errors:
        return EditResult(None, errors)

    new_content = "".join(text + ending for text, ending in entries)
    if new_content == content:
        return EditResult(None, ["the edits did not change the file"])
    return EditResult(new_content, [])


def apply_edit_response(content, reply):
    """Parses a model reply and applies it to `content`. Never raises for bad replies."""
    try:
        blocks = parse_blocks(reply)
    except EditFormatError as error:
        return EditResult(None, [str(error)])
    return apply_blocks(content, blocks)


def feedback_for(reply, errors):
    """Text appended to the next prompt so the model can correct its previous reply."""
    problems = "\n".join(f"- {error}" for error in errors)
    return ("\n\nYour previous reply could not be applied.\n"
            f"Problems:\n{problems}\n\n"
            "Your previous reply was:\n"
            f"{reply}\n\n"
            "Reply again with corrected SEARCH/REPLACE blocks, copying the SEARCH lines "
            "exactly from the file shown above.")
