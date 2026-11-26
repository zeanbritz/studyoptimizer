MAX_PROMPT_LENGTH = 10_000
MAX_ANSWER_LENGTH = 5_000
# Allow space for six answers, their labels, and pasted headings.
MAX_SINGLE_IMPORT_LENGTH = MAX_PROMPT_LENGTH + 6 * MAX_ANSWER_LENGTH + 2_000
