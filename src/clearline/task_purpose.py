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


def agent_managed_task(task):
    """Pure reconsideration after evidence is Clearline's job, not a missing fact.

    Deliberately narrow: never remove a mixed identity, recipient, evidence
    collection or order verification task because its reasoning says "reassess".
    """
    title = task['title'].casefold().strip().rstrip('.')
    # A mixed request to establish facts is still human work. References to
    # completed evidence in an "after ..." clause are not new instructions.
    if re.search(r'(?:and|then|;)\s*(?:also\s+)?(?:verify|establish|collect|confirm|obtain|identify|request|resolve|document|record)\b', title):
        return False
    leading = re.split(r'\s+(?:after|once|using|based on|following)\s+', title, maxsplit=1)[0]
    if re.search(r'\b(?:contact|recipient|authori[sz]ation|permission|jurisdiction|identity|route|evidence|cause|status|reason for)\b', leading):
        return False
    return bool(
        re.match(r'^(?:reassess|re-evaluate|reevaluate|requalify|reconsider)\b', leading)
        and re.search(r'\b(?:opportunit(?:y|ies)|signals?|declines?|deterioration|recovery need|commercial strategy)\b', leading)
        or re.match(r'^reconcile (?:the )?verified (?:order|credit|billing|support) (?:disposition|finding|outcome) with (?:the )?(?:decline|commercial|recovery|expansion) assessment$', title)
        or re.match(r'^reconcile (?:the )?findings with (?:the )?(?:pending|existing) draft before (?:any )?approval', title)
        or re.match(r'^record (?:the )?monitoring decision against (?:the )?pending .*draft$', title)
    )
