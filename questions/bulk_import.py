import re

from .text_limits import MAX_ANSWER_LENGTH, MAX_PROMPT_LENGTH


MAX_BATCH_QUESTIONS = 50
MAX_PASTE_LENGTH = 200_000

EXPLICIT_QUESTION = re.compile(r"^(?:question|q)\s*(\d+)(?:[.):]\s*|\s+|$)", re.I)
NUMBERED_QUESTION = re.compile(r"^(\d+)[.)]\s+")
OPTION = re.compile(r"^(?:\(([a-z]|\d{1,2})\)|([a-z]|\d{1,2})[.):])(?:\s+(.*)|$)", re.I)
BULLET = re.compile(r"^[-*•◦▪●]\s+(.+)")
CHOICE_HEADING = re.compile(r"^(?:possible answers|answers|(?:answer )?(?:options|choices))\s*:?$", re.I)
ANSWER_LINE = re.compile(r"^(?:correct\s+)?answers?\s*:\s*(.*)$", re.I)
ANSWER_KEY = re.compile(r"^answer\s+key\s*:\s*$", re.I)
KEY_ITEM = re.compile(r"^(\d+)[.):]\s*(.+)$")
KEY_LETTERS = re.compile(r"[a-f1-6](?:\s*(?:[,;/&+]|\band\b)\s*[a-f1-6])*", re.I)


def _option(line):
    if bullet := BULLET.match(line):
        return ("bullet", None, bullet[1])
    if match := OPTION.match(line):
        label = match[1] or match[2]
        style = "number" if label.isdecimal() else "letter"
        number = int(label) if style == "number" else ord(label.upper()) - ord("A") + 1
        return (style, number, match[3] or "")
    return None


def _question_blocks(lines):
    # A numbered choice list can be separated by blank lines or explicit Q1/Q2 headings.
    starts = [index for index, line in enumerate(lines) if EXPLICIT_QUESTION.match(line)]
    if not starts:
        numbered = [index for index, line in enumerate(lines) if NUMBERED_QUESTION.match(line)]
        # A numbered line is a question heading when the block has lettered
        # or bulleted choices. This leaves numbered answers in plain blocks alone.
        starts = [
            start
            for start, end in zip(numbered, numbered[1:] + [len(lines)])
            if any((option := _option(line)) and option[0] != "number" for line in lines[start + 1:end])
        ]
    if starts:
        if any(_option(line) for line in lines[:starts[0]]):
            starts.insert(0, next(index for index, line in enumerate(lines) if line))
        return [lines[start:end] for start, end in zip(starts, starts[1:] + [len(lines)])]

    blocks = []
    separator = True
    for line in lines:
        if not line:
            separator = True
            continue
        continues_block = _option(line) or ANSWER_LINE.match(line) or CHOICE_HEADING.match(line)
        if not blocks or (separator and not continues_block):
            blocks.append([])
        blocks[-1].append(line)
        separator = False
    return blocks


def _answer_numbers(answer, choices):
    # Preselect a written key only when every label is clear and available.
    answer = answer.strip().rstrip(".").strip()
    if not KEY_LETTERS.fullmatch(answer):
        return []
    labels = re.split(r"\s*(?:[,;/&+]|\band\b)\s*", answer.upper(), flags=re.I)
    numbers = {int(label) if label.isdecimal() else ord(label) - ord("A") + 1 for label in labels}
    return sorted(numbers) if all(1 <= n <= len(choices) for n in numbers) else []


def _parse_block(block, answer_key, index):
    lines = [line for line in block if line]
    heading = EXPLICIT_QUESTION.match(lines[0]) or NUMBERED_QUESTION.match(lines[0])
    if heading:
        lines[0] = lines[0][heading.end():].strip()
        lines = [line for line in lines if line]
    if not lines:
        raise ValueError(f"Question {index} is missing its text.")

    quiz_number = int(heading[1]) if heading else index
    written_answer = answer_key.get(quiz_number, "")
    prompt = [lines[0]]
    choices = []
    option_style = None
    for line in lines[1:]:
        if key := ANSWER_LINE.match(line):
            written_answer = key[1]
            break
        if CHOICE_HEADING.match(line) and not choices:
            continue
        option = _option(line)
        if option and option_style in (None, option[0]):
            style, number, choice = option
            if number is not None and number != len(choices) + 1:
                raise ValueError(f"Question {index} has answer labels out of order. Use A, B, C or 1, 2, 3.")
            option_style = style
            choices.append(choice)
        elif choices:
            choices[-1] = f"{choices[-1]} {line}".strip()
        else:
            prompt.append(line)

    if not choices:
        # For plain text, the first line is the question and each other line is one answer.
        prompt, choices = prompt[:1], prompt[1:]
    text = "\n".join(prompt)
    if not 2 <= len(choices) <= 6 or not all(choices):
        raise ValueError(f"Question {index} needs two to six answers. Put each answer on its own line.")
    if len(text) > MAX_PROMPT_LENGTH:
        raise ValueError(f"Question {index} exceeds the {MAX_PROMPT_LENGTH:,}-character limit for question text.")
    for number, choice in enumerate(choices, 1):
        if len(choice) > MAX_ANSWER_LENGTH:
            raise ValueError(f"Answer {number} in question {index} exceeds the {MAX_ANSWER_LENGTH:,}-character limit.")

    return {
        "prompt": text,
        "answer_count": len(choices),
        "correct": _answer_numbers(written_answer, choices),
        **{f"answer_{number}": choice for number, choice in enumerate(choices, 1)},
    }


def parse_quiz_text(source):
    lines = [line.strip() for line in source.splitlines()]
    answer_key = {}
    for index, line in enumerate(lines):
        if ANSWER_KEY.match(line):
            for entry in lines[index + 1:]:
                if item := KEY_ITEM.match(entry):
                    answer_key[int(item[1])] = item[2]
            lines = lines[:index]
            break

    blocks = _question_blocks(lines)
    if not blocks:
        raise ValueError("Paste at least one question with its answer choices.")
    if len(blocks) > MAX_BATCH_QUESTIONS:
        raise ValueError(f"Import up to {MAX_BATCH_QUESTIONS} questions at a time.")
    return [_parse_block(block, answer_key, index) for index, block in enumerate(blocks, 1)]
