#!/usr/bin/env python3
"""Persist coordinator tokens and host handles; never launch agents or infer liveness."""
import argparse
import json
from pathlib import Path
import sys
import uuid


def identity(path):
    path = Path(path).resolve()
    value = {'coordinator': 'coordinator-' + str(uuid.uuid4()), 'purpose': 'local-coordinator-token'}
    # The token is an ownership label, not a host context ID or isolation evidence.
    with path.open('x', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False)
    return {'coordinator_file': str(path)}


def owner(path):
    with Path(path).open(encoding='utf-8') as f:
        value = json.load(f)
    if value.get('purpose') != 'local-coordinator-token' or not isinstance(value.get('coordinator'), str) or not value['coordinator'].strip():
        raise ValueError('无效协调身份文件')
    return value['coordinator']


def records(work):
    path = Path(work) / 'host-tasks.json'
    if not path.exists():
        return {}
    with path.open(encoding='utf-8') as f:
        value = json.load(f)
    if not isinstance(value, dict):
        raise ValueError('host-tasks.json 必须为对象')
    return value


def key(job):
    return '{}@{}'.format(job['id'], job['attempt'])


def bound(work, job):
    entry = records(work).get(key(job), {})
    return entry.get('handle') if entry.get('ticket') == job['ticket'] and not entry.get('released') else None


def main():
    import tasks
    import report
    import workflow as wf
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='command', required=True)
    token = subs.add_parser('identity')
    token.add_argument('--output', required=True)
    lookup = subs.add_parser('lookup')
    lookup.add_argument('--work', required=True)
    lookup.add_argument('--handle', required=True)
    for command in ('bind', 'bind-many', 'release'):
        p = subs.add_parser(command)
        p.add_argument('--work', required=True)
        group = p.add_mutually_exclusive_group(required=True)
        group.add_argument('--coordinator')
        group.add_argument('--coordinator-file')
        if command == 'bind-many':
            p.add_argument('--bindings', required=True, help='JSON 列表文件，每项为 event 和 handle；全部校验后一次写入')
        else:
            p.add_argument('--event', required=True, help='dispatch 返回的 task@attempt')
            if command == 'bind': p.add_argument('--handle', required=True)
            else: p.add_argument('--confirmed-not-running', action='store_true', required=True)
    args = parser.parse_args()
    try:
        if args.command == 'identity':
            target = Path(args.output).resolve()
            report.require(target != tasks.SKILL and tasks.SKILL not in target.parents, '身份文件须放在技能包之外')
            print(json.dumps(identity(args.output), ensure_ascii=False)); return 0
        work = Path(args.work).resolve()
        if args.command == 'lookup':
            found = [{'event': event, **entry} for event, entry in records(work).items() if entry.get('handle') == args.handle]
            report.require(len(found) == 1, '宿主句柄没有唯一映射，请核对派发记录')
            state = wf.load(work / 'task-state.json')
            value = found[0]
            value['handled'] = value['event'] in state.get('handled_events', [])
            print(json.dumps(value, ensure_ascii=False)); return 0
        coordinator = owner(args.coordinator_file) if args.coordinator_file else args.coordinator
        with tasks.coordinator_lock(work):
            state = wf.load(work / 'task-state.json')
            report.require(state.get('coordinator', {}).get('id') == coordinator, '协调身份不匹配；先显式接管')
            data = records(work)
            if args.command in ('bind', 'bind-many'):
                items = wf.load(args.bindings) if args.command == 'bind-many' else [{'event': args.event, 'handle': args.handle}]
                report.require(isinstance(items, list) and items, '绑定列表不能为空')
                for item in items:
                    report.obj(item, 'binding')
                    event, handle = report.string(item.get('event'), 'event'), report.string(item.get('handle'), 'handle')
                    job = next((j for j in state['jobs'].values() if key(j) == event), None)
                    report.require(job is not None, '通知标识不对应当前任务轮次')
                    report.require(not any(e.get('handle') == handle and k != event for k, e in data.items()), '宿主句柄已绑定另一轮任务')
                    old = data.get(event)
                    report.require(not old or old.get('released') or old.get('handle') == handle, '任务已绑定其他句柄，请先核对宿主')
                    data[event] = {'handle': handle, 'ticket': job['ticket'], 'recorded_at': tasks.now(), 'released': False}
                events = list(dict.fromkeys(item['event'] for item in items))
            else:
                job = next((j for j in state['jobs'].values() if key(j) == args.event), None)
                report.require(job is not None, '通知标识不对应当前任务轮次')
                report.require(job['status'] == 'assigned' and not Path(job['job_path'] + '.started').exists()
                               and not Path(job['response_path']).exists(), '只可释放尚未领取且没有结果的派发记录')
                report.require(args.event in data, '没有可释放的派发记录')
                data[args.event].update(released=True, released_at=tasks.now())
                events = [args.event]
            tasks.save(work / 'host-tasks.json', data, (work / 'host-tasks.json').exists())
        result = {'events': events, 'recorded': True}
        if args.command != 'bind-many':
            result['event'] = args.event
        print(json.dumps(result, ensure_ascii=False))
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print('错误：' + str(exc), file=sys.stderr); return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
