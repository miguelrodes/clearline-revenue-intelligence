"""Select the existing task's input form without changing its commercial decision."""
import re


def task_purpose(task):
    # Reasons describe boundaries too (e.g. "not a task to solicit a new
    # contact" or "record the authorized next step"). Those are not the task.
    title = task['title'].casefold()
    identity = bool(re.search(r'identity|\bmatch|mapping|alias', title))
    contact = bool(re.search(r'contact|recipient|authoriz|permission|\brout(?:e|ing)\b|purchasing relationship', title))
    return {'contact_check': contact, 'identity_check': identity,
            'contact_resolvable': contact and not identity}
