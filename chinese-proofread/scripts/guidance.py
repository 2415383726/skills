#!/usr/bin/env python3
"""Build a task-local reading packet; this does not enforce filesystem isolation."""
import argparse
from difflib import SequenceMatcher
import json
from pathlib import Path
import sys
import unicodedata

REFERENCES = Path(__file__).resolve().parents[1] / 'references'
ROLES = ('proofread', 'review', 'consistency')
DOMAINS = ('text', 'punctuation', 'names')


def sources(role, payload=None, chat=False):
    if role not in ROLES:
        raise ValueError('未知角色：' + str(role))
    selected = set()
    if role == 'proofread':
        selected.update(('text', 'punctuation'))
    elif role == 'consistency':
        selected.add('names')
    elif payload is None:
        selected.update(DOMAINS)
    else:
        for group in payload.get('candidate_groups', []):
            for candidate in group['candidates']:
                rule = candidate.get('rule_id', '')
                if rule.startswith(('T-', 'W-')):
                    selected.add('text')
                elif rule.startswith('P-'):
                    selected.add('punctuation')
                elif rule.startswith('N-'):
                    selected.add('names')
                else:
                    selected.update(DOMAINS)
                # Include rules for actual edits, even if the initial label is wrong.
                anchors = candidate.get('anchors', [])
                if len(anchors) > 1:
                    selected.add('names')
                if candidate.get('suggestion') is not None and anchors:
                    original, replacement = anchors[0]['quote'], candidate['suggestion']
                    for op, a, b, c, d in SequenceMatcher(None, original, replacement, autojunk=False).get_opcodes():
                        if op == 'equal':
                            continue
                        changed = original[a:b] + replacement[c:d]
                        if any(char.isalnum() for char in changed):
                            selected.add('text')
                        if any(unicodedata.category(char).startswith(('P', 'S', 'Z', 'C')) for char in changed):
                            selected.add('punctuation')
    files = ['rules.md', 'roles/' + role + '.md']
    files.extend('checks/' + domain + '.md' for domain in DOMAINS if domain in selected)
    if not chat:
        files.append('formats/' + role + '.md')
    return files


def draft(role, payload):
    if role == 'proofread':
        return {'completed': False, 'checked_unit_ids': [], 'candidates': [], 'terms': [], 'limitations': []}
    if role == 'consistency':
        return {'checked': False, 'candidates': [], 'limitations': []}
    return {'group_decisions': [{'group_id': group['id'], 'accept': [], 'reject': [], 'replace': []}
                               for group in payload['candidate_groups']], 'limitations': []}


def all_sources():
    return ['rules.md', 'rule-catalog.json', 'roles/chat.md'] + [
        folder + '/' + name + '.md' for folder, names in
        (('roles', ROLES), ('checks', DOMAINS), ('formats', ROLES)) for name in names]


def compose(role, payload=None, chat=False):
    files = sources(role, payload, chat)
    if chat:
        files.append('roles/chat.md')
    text = '\n\n'.join((REFERENCES / name).read_text(encoding='utf-8').strip() for name in files)
    return text + '\n', files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--role', required=True, choices=ROLES)
    parser.add_argument('--input', help='复核任务 JSON；不提供时保留全部领域判据')
    parser.add_argument('--chat', action='store_true')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    import report
    try:
        payload = report.load_json(args.input) if args.input else None
        text, files = compose(args.role, payload, args.chat)
        target = Path(args.output).resolve()
        skill = REFERENCES.parent
        report.require(target != skill and skill not in target.parents, '任务指引须生成在技能包之外')
        report.write_output(str(target), text, False, [str(REFERENCES / f) for f in files] + ([args.input] if args.input else []))
        print(json.dumps({'guidance_path': str(target), 'role': args.role}, ensure_ascii=False))
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print('错误：' + str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
