"""Ordered human-review routing; never grants access."""
from copy import deepcopy
from datetime import date
import re
from .validation import instruction_override, source_conflicts

REQUIRED = ('request_id', 'request_date', 'requester', 'team', 'system', 'environment',
            'permission', 'business_purpose', 'start_date', 'end_date', 'manager')


def route(document, result):
    result = deepcopy(result)
    if result['error']:
        return result
    facts = result['extraction']
    issues = facts['issues']
    def issue(text):
        if text not in issues:
            issues.append(text)
    mismatch = (document.filename_request_id and facts['request_id'] and
                document.filename_request_id != facts['request_id'])
    if mismatch:
        issue('request_id mismatch between filename and stated message identifier.')
    bad_date = False
    for field in ('request_date', 'start_date', 'end_date'):
        if facts[field]:
            try:
                date.fromisoformat(facts[field])
            except ValueError:
                bad_date = True
                issue(f'{field} is not a valid calendar date; clarify.')
    reversed_dates = (facts['start_date'] and facts['end_date'] and
                      facts['start_date'] > facts['end_date'])
    if reversed_dates:
        issue('start_date is after end_date; clarify dates without swapping them.')
    if instruction_override(document.message) or any(
        re.search(r'\b(instruction.override|injection|override attempt)\b', i, re.I) for i in issues
    ):
        owner, status, action, rule = 'IT Service Desk', 'review', 'inspect-message', 1
    elif facts['kind'] == 'withdrawal' and facts['request_id'] and facts['request_date']:
        owner, status, action, rule = 'IT Service Desk', 'review', 'confirm-withdrawal', 2
    elif (facts['kind'] not in ('new', 'change') or mismatch or bad_date or reversed_dates
          or any(not facts[f] for f in REQUIRED) or source_conflicts(document.message)
          or any(re.search(r'\bconflict|\bcontradict|\bmismatch', i, re.I) for i in issues)):
        owner, status, action, rule = 'IT Service Desk', 'needs-information', 'clarify', 3
    elif facts['environment'] == 'production' or facts['permission'] in ('write', 'admin'):
        owner, status, action, rule = 'Security Review', 'review', 'review-risk-then-owner', 4
    else:
        owner, status, action, rule = 'System Owner', 'review', 'review-request', 5
    result.update(owner=owner, status=status, next_action=action, policy_rule=rule)
    return result
