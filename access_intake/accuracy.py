"""Independent field comparison with explicit missing-result penalties."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCALARS = ('request_id','request_date','kind','requester','team','system','environment',
           'permission','start_date','end_date','manager')
# Implementation interpretations of the source/policy, not new policy requirements.
INTERPRETATIONS = {('IT-006.json', 'permission'): 'read',
                   ('IT-014.json', 'start_date'): '2026-11-05',
                   ('IT-014.json', 'end_date'): '2026-11-02'}


def compare(records, expectations):
    by_id = {}
    for row in records:
        if row['document_id'] in by_id:
            raise ValueError('Duplicate document in measured records.')
        by_id[row['document_id']] = row
    matched, mismatches, routes, whole, ambiguous = 0, [], 0, 0, 0
    for expected in expectations:
        doc = expected['document_id']
        row = by_id.get(doc)
        facts = row.get('extraction') if row and not row.get('error') else None
        ok = True
        for field in SCALARS:
            value = expected['facts'][field]
            if isinstance(value, dict):
                value = INTERPRETATIONS[(doc, field)]
                ambiguous += 1
            if facts is not None and facts.get(field) == value:
                matched += 1
            else:
                ok = False
                mismatches.append({'document_id': doc, 'field': field, 'expected': value,
                                   'actual': facts.get(field) if facts else '[extraction unavailable]'})
        whole += int(ok)
        routes += int(row is not None and all(row.get(k) == expected['route'][k] for k in ('status','owner','next_action')))
    return dict(exact_matches=matched, denominator=len(expectations)*len(SCALARS),
                whole_document_matches=whole, documents=len(expectations), route_matches=routes,
                interpretation_dependent_fields=ambiguous, mismatches=mismatches)


def write_accuracy(records, path):
    expectations = [json.loads(p.read_text()) for p in sorted((ROOT/'tests/expectations').glob('*.json'))]
    result = compare(records, expectations)
    sources = sorted({r['response_source'] for r in records})
    lines = ['# Source-grounded accuracy check', '',
             f'Observation: response sources `{sources}`. Mock scores test fixture plumbing and comparison only; they do not measure language-model quality. No live observation was performed.', '',
             'Reproduce: `python3 -m access_intake accuracy --db var/intake.sqlite`.', '',
             'Configuration for each measured attempt is retained in extractions.jsonl `processing_settings` and `settings_sha256`. The real adapter default is OpenAI gpt-4.1-mini-2025-04-14, temperature 0, 2500 output tokens, strict native JSON Schema, store=false. Mock fixture hashes identify the saved replies.', '',
             '## Procedure and counting', '',
             'Expected facts in tests/expectations predate this repair and were written from decoded message text and office policy, independently of measured outputs. Full expected facts and source/policy annotations are reproduced below. Compare 11 scalar fields with exact case-sensitive equality, including nulls. Denominator is fixed at 21 × 11 = 231; missing or failed extractions score 11 mismatches, even when an expected value is null. Duplicate documents are rejected. Additional documents are ignored for this corpus score.', '',
             'Three scalar expectations were left open in the original research. This report uses disclosed implementation interpretations: IT-006 permission read (injected commands are data, not a replacement access request); IT-014 retains the two individually explicit reversed dates, with a date-order issue and clarification. These 3 comparisons depend on those interpretations; 228 comparisons are settled. Policy-owner confirmation remains a handover item.', '',
             'business_purpose is excluded from exact matching because equivalent faithful summaries differ in wording. Its source quotations/rubric are listed for human comparison: check all claims against the quoted message, mark missing intent or unsupported claims as factual errors. Likewise review issue coverage, conflicts/corrections and exact quote validity separately; no automated semantic-purpose score is claimed.', '',
             'Factual-error reporting: every scalar disagreement is listed with document, field, expected and actual. Count invented non-null values, wrong alternatives and unsupported purposes separately during human review; a mock score supplies no evidence of live factual accuracy. Compare any future model/prompt change with this same oracle and denominator, keeping separate result files and response_source/configuration.', '',
             '## Observed comparison', '', '```json', json.dumps(result,indent=2), '```', '',
             'Baseline: the pre-repair application had no executable intake or current outputs. Under this fixed-denominator procedure that missing-output baseline is 0/231 (unavailable records, not an observed model score). The mock comparison above shows pipeline completion only. No assistant-versus-assistant or live model improvement is claimed.', '',
             '## Expected fields and evidence', '']
    for expected in expectations:
        lines.extend([f"### {expected['document_id']}", '',
                      f"Source: `{expected['source_path']}`; policy: `materials/office-policy.md`.", '',
                      '```json', json.dumps({k:expected[k] for k in ('facts','annotations','purpose_rubric','issue_fields','route')},indent=2), '```', ''])
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return result
