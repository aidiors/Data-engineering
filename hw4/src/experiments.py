import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import psutil
from kazoo.handlers.threading import KazooTimeoutError
from kazoo.exceptions import ConnectionLoss, SessionExpiredError

from .calculation import prepare
from .cluster import CREATE_NO_WINDOW, Ensemble, terminate, wait_for
from .zk_common import ROOT, client, encode, event, load_ref, save


def read_events(path):
    if not Path(path).exists():
        return []
    lines = Path(path).read_text(encoding='utf-8').splitlines()
    result = []
    for line in lines:
        try:
            result.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return result


def find_event(path, kind, predicate=lambda row: True):
    return next((r for r in read_events(path) if r['event'] == kind and predicate(r)), None)


def stage1(ensemble):
    directory = ROOT / 'logs/stage1'
    directory.mkdir(parents=True, exist_ok=True)
    log = directory / 'events.jsonl'
    statuses = wait_for(ensemble.ready)
    for number, status in enumerate(statuses, 1):
        event(log, 'initial_role', server=number, output=status)
    followers = [i for i, status in enumerate(statuses, 1) if 'Mode: follower' in status]
    zk = client()
    try:
        zk.ensure_path('/hw4')
        if not zk.exists('/hw4/probe'):
            zk.create('/hw4/probe', b'initial')
        ensemble.stop(followers[0])
        zk.set_async('/hw4/probe', b'one-down').get(timeout=8)
        actual = zk.get('/hw4/probe')[0].decode()
        assert actual == 'one-down'
        event(log, 'one_server_down', stopped=followers[:1], write_read=actual, available=True)
        ensemble.stop(followers[1])
        started = time.monotonic()
        try:
            zk.set_async('/hw4/probe', b'two-down-probe').get(timeout=5)
        except (KazooTimeoutError, ConnectionLoss, SessionExpiredError) as exc:
            event(log, 'two_servers_down', stopped=followers, available=False,
                  elapsed_seconds=time.monotonic() - started, error=type(exc).__name__,
                  remaining_server=next(i for i in (1, 2, 3) if i not in followers),
                  output=ensemble.status(next(i for i in (1, 2, 3) if i not in followers)))
        else:
            raise AssertionError('Write unexpectedly succeeded without quorum')
    finally:
        for number in followers:
            ensemble.start(number)
        wait_for(ensemble.ready)
        zk.stop()
        zk.close()
    zk = client()
    path = '/hw4/ephemeral-demo'
    if zk.exists(path):
        raise RuntimeError('Old ephemeral test is still active')
    process = ensemble.cli('create -e /hw4/ephemeral-demo live\n', directory / 'zkCli-create.txt')
    try:
        stat = wait_for(lambda: zk.exists(path), 15)
        event(log, 'ephemeral_created', path=path, ephemeral_owner=stat.ephemeralOwner)
        before_close = time.monotonic()
        terminate(process.pid)
        process.stdin.close()
        wait_for(lambda: not zk.exists(path), 45)
        event(log, 'ephemeral_disappeared', path=path, exists=False,
              seconds_after_client_close=time.monotonic() - before_close)
        check = ensemble.cli('get /hw4/ephemeral-demo\nquit\n', directory / 'zkCli-after-close.txt')
        check.stdin.close()
        check.wait(timeout=15)
        event(log, 'ensemble_restored', outputs=[ensemble.status(i) for i in (1, 2, 3)])
    finally:
        terminate(process.pid)
        zk.stop()
        zk.close()
    save(directory / 'summary.json', {'passed': True, 'events': read_events(log)})


def launch(script, args, directory, name):
    with (directory / (name + '.console.log')).open('wb') as stream:
        return subprocess.Popen([sys.executable, '-u', '-m', 'src.' + Path(script).stem, *args], cwd=ROOT,
                                stdout=stream, stderr=subprocess.STDOUT,
                                creationflags=CREATE_NO_WINDOW,
                                env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})


def failover(fencing, cap=5, pause_seconds=40, fixture=None):
    run = ('selftest-' if fixture else '') + f'fencing-{fencing}-cap-{cap}-' + time.strftime('%Y%m%d-%H%M%S')
    directory = ROOT / 'logs' / run
    directory.mkdir(parents=True)
    log = directory / 'experiment.jsonl'
    base = '/hw4/' + run
    zk = client()
    zk.ensure_path(base)
    for path, value in [('epoch', b'0'), ('checkpoint', b'null'), ('result', b'null'), ('publications', b'')]:
        zk.create(base + '/' + path, value)
    receiver = first = second = None
    suspended = False
    suspended_pid = None
    try:
        receiver = launch('receiver.py', ['--run', run, '--fencing', str(fencing), '--port', '0'], directory, 'receiver')
        ready = wait_for(lambda: find_event(directory / 'receiver.jsonl', 'ready'), 15)
        arguments = ['--run', run, '--cap', str(cap), '--port', str(ready['port']), '--demonstrate-stale-work']
        if fixture:
            arguments.extend(['--input', str(fixture / 'frontend.jsonl'),
                              '--provenance', str(fixture / 'provenance.json')])
        first = launch('coordinator.py', [*arguments, '--name', 'A'], directory, 'A')
        wait_for(lambda: find_event(directory / 'A.jsonl', 'leader'), 15)
        second = launch('coordinator.py', [*arguments, '--name', 'B'], directory, 'B')
        checkpoint = wait_for(lambda: find_event(directory / 'A.jsonl', 'checkpoint', lambda r: r['next_row'] >= 600), 20)


        first_started = find_event(directory / 'A.jsonl', 'started')
        second_started = wait_for(lambda: find_event(directory / 'B.jsonl', 'started'), 5)
        assert first_started['negotiated_session_timeout_ms'] == 10000
        assert second_started['negotiated_session_timeout_ms'] == 10000
        suspended_pid = first_started['pid']

        suspended_at = time.monotonic_ns()
        psutil.Process(suspended_pid).suspend()
        suspended = True
        checkpoint_row = load_ref(json.loads(zk.get(base + '/checkpoint')[0]))['next_row']
        event(log, 'suspended', coordinator='A', pid=suspended_pid,
              suspension_monotonic_ns=suspended_at, checkpoint_row=checkpoint_row)
        leader = wait_for(lambda: find_event(directory / 'B.jsonl', 'leader'), 25)
        elapsed = (leader['monotonic_ns'] - suspended_at) / 1e9
        restored = wait_for(lambda: find_event(directory / 'B.jsonl', 'restored'), 5)
        assert restored['next_row'] > 0
        assert restored['next_row'] == checkpoint_row
        assert restored['next_row'] < (1800 if fixture else 6057)
        event(log, 'failover_measured', seconds=elapsed, new_leader='B',
              restored_next_row=restored['next_row'])
        second.wait(timeout=30)
        assert second.returncode == 0, (directory / 'B.console.log').read_text(encoding='utf-8')
        remaining = pause_seconds - (time.monotonic_ns() - suspended_at) / 1e9
        if remaining > 0:
            time.sleep(remaining)
        psutil.Process(suspended_pid).resume()
        suspended = False
        event(log, 'resumed', coordinator='A', actual_pause_seconds=(time.monotonic_ns() - suspended_at) / 1e9)
        first.wait(timeout=45)
        assert first.returncode == 0, (directory / 'A.console.log').read_text(encoding='utf-8')
        receiver_events = read_events(directory / 'receiver.jsonl')
        publications = [r for r in receiver_events if r['event'] == 'published']
        rejections = [r for r in receiver_events if r['event'] == 'rejected']
        pointer_bytes, stat = zk.get(base + '/result')
        pointer = json.loads(pointer_bytes)
        assert len(publications) == (1 if fencing else 2)
        assert len(rejections) == (1 if fencing else 0)
        assert stat.version == (1 if fencing else 2)
        assert pointer['coordinator'] == ('B' if fencing else 'A')
        journal = {key: json.loads(zk.get(base + '/publications/' + key)[0])
                   for key in sorted(zk.get_children(base + '/publications'))}
        assert len(journal) == len(publications)

        reference_path = (fixture / 'reference.json') if fixture else ROOT.parent / 'hw3/output/counts' / f"mr_{cap if cap else 'all'}.json"
        reference = json.loads(reference_path.read_text(encoding='utf-8'))
        from frontend_lake.validation import compare
        verification = {}
        for name in ('A', 'B'):
            attempted = find_event(directory / f'{name}.jsonl', 'publish_attempt')
            actual = load_ref(attempted['result'])
            digest = compare(reference, actual)
            verification[name] = {'equal_to_reference': True, 'equal_to_hw3': not bool(fixture), 'sha256_counts': digest,
                                  'sum_frequencies': actual['sum_frequencies'],
                                  'unique_combinations': actual['unique_combinations'],
                                  'source_rows': actual['source_rows'], 'selected_rows': actual['selected_rows']}
        summary = {'run': run, 'dataset_kind': 'synthetic-self-test' if fixture else 'hw3',
                   'fencing': fencing, 'cap': cap, 'session_timeout_ms': 10000,
                   'pause_seconds': pause_seconds, 'failover_seconds': elapsed,
                   'restored_next_row': restored['next_row'],
                   'publication_count': len(publications), 'rejection_count': len(rejections),
                   'pointer_version': stat.version, 'pointer': pointer,
                   'journal': journal, 'verification': verification}
        save(directory / 'summary.json', summary)
        event(log, 'all_assertions_passed', summary=summary)
        return summary
    finally:
        if suspended and suspended_pid:
            try:
                psutil.Process(suspended_pid).resume()
            except psutil.NoSuchProcess:
                pass
        for process in (first, second, receiver):
            if process and process.poll() is None:
                terminate(process.pid)
        zk.stop()
        zk.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('prepare', 'stage1', 'failover', 'all', 'selftest'))
    parser.add_argument('--csv', type=Path)
    parser.add_argument('--cap', type=int, default=5)
    parser.add_argument('--fencing', type=int, choices=(0, 1), default=1)
    args = parser.parse_args()
    if args.stage == 'prepare':
        if not args.csv:
            parser.error('--csv is required')
        provenance = prepare(args.csv, ROOT / 'data/frontend.jsonl')
        save(ROOT / 'data/provenance.json', provenance)
        print(json.dumps(provenance, ensure_ascii=False))
        return
    ensemble = Ensemble()
    wait_for(ensemble.ready)
    if args.stage in ('stage1', 'all'):
        stage1(ensemble)
    if args.stage == 'failover':
        failover(args.fencing, args.cap)
    elif args.stage == 'all':
        summaries = [failover(fencing, args.cap) for fencing in (0, 1)]
        save(ROOT / 'logs/summary.json', summaries)
    elif args.stage == 'selftest':
        from .selftest_data import create_fixture
        fixture = create_fixture()
        summaries = [failover(fencing, 5, fixture=fixture) for fencing in (0, 1)]
        save(ROOT / 'logs/selftest-summary.json', summaries)


if __name__ == '__main__':
    main()
