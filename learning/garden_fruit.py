"""Permanent, reusable subject fruit designs (independent of event type)."""

FRUIT_CHOICES = (
    ("red-apple", "Red apple"),
    ("pear", "Pear"),
    ("peach", "Peach"),
    ("green-apple", "Green apple"),
    ("yellow-apple", "Yellow apple"),
    ("red-pear", "Red pear"),
)


def available_fruit(subjects):
    """Use each design before reusing the least common one."""
    counts = {key: 0 for key, _ in FRUIT_CHOICES}
    for fruit in subjects.values_list("garden_fruit", flat=True):
        if fruit in counts:
            counts[fruit] += 1
    return min(counts, key=counts.get)
