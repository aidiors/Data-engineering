import argparse
import json
import os
import time
import urllib.error
import urllib.request

from kazoo.exceptions import BadVersionError, NodeExistsError, KazooException

from .calculation import empty, process, result
from .zk_common import ROOT, client, commit, encode, event, immutable, load_ref


def claim(zk, base, name):
    _, stat = zk.get(base + '/epoch')
    epoch = stat.version + 1
    tx = zk.transaction()
    tx.check(base + '/epoch', version=stat.version)
    tx.set_data(base + '/epoch', str(epoch).encode(), version=stat.version)
    tx.create(base + '/leader', encode({'name': name, 'epoch': epoch}), ephemeral=True)
    commit(tx)
    return epoch


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--run', required=True)
    p.add_argument('--name', required=True)
    p.add_argument('--cap', type=int, default=5)
    p.add_argument('--chunk', type=int, default=150)
    p.add_argument('--delay', type=float, default=0.3)
    p.add_argument('--port', type=int, default=8765)
    p.add_argument('--input', default=str(ROOT / 'data/frontend.jsonl'))
    p.add_argument('--provenance', default=str(ROOT / 'data/provenance.json'))
    p.add_argument('--demonstrate-stale-work', action='store_true')
    args = p.parse_args()
    log = ROOT / 'logs' / args.run / (args.name + '.jsonl')
    base = '/hw4/' + args.run
    zk = client(timeout=10)
    zk.add_listener(lambda state: event(log, 'session', state=str(state)))
    event(log, 'started', pid=os.getpid(), requested_session_timeout_ms=10000,
          negotiated_session_timeout_ms=zk._session_timeout)
    try:
        while True:
            if json.loads(zk.get(base + '/result')[0]):
                event(log, 'already_completed')
                return
            try:
                epoch = claim(zk, base, args.name)
                break
            except (NodeExistsError, BadVersionError):
                time.sleep(0.1)
        event(log, 'leader', epoch=epoch)
        ref = json.loads(zk.get(base + '/checkpoint')[0])
        state = load_ref(ref) if ref else empty()
        event(log, 'restored', next_row=state['next_row'], checkpoint=ref)
        from pathlib import Path
        provenance = json.loads(Path(args.provenance).read_text(encoding='utf-8'))
        prepared = Path(args.input)
        import hashlib
        with prepared.open('rb') as stream:
            actual_hash = hashlib.file_digest(stream, 'sha256').hexdigest()
        if actual_hash != provenance['prepared_sha256']:
            raise ValueError('Input changed after preparation')
        rows = [json.loads(line) for line in prepared.read_text(encoding='utf-8').splitlines()]
        can_checkpoint = True
        while state['next_row'] < len(rows):
            start = state['next_row']
            state = process(state, rows[start:start + args.chunk], args.cap)
            if can_checkpoint:
                ref = immutable(ROOT / 'logs' / args.run / 'objects', state)
                tx = zk.transaction()
                tx.check(base + '/epoch', version=epoch)
                tx.set_data(base + '/checkpoint', encode(ref))
                try:
                    commit(tx)
                    event(log, 'checkpoint', next_row=state['next_row'], epoch=epoch, checkpoint=ref)
                except KazooException as exc:
                    event(log, 'checkpoint_rejected', error=type(exc).__name__, epoch=epoch)
                    if not args.demonstrate_stale_work:
                        raise
                    can_checkpoint = False
                    event(log, 'demo_stale_work_continues', epoch=epoch)
            time.sleep(args.delay)
        calculated = result(state, args.cap, provenance['source_rows'])
        ref = immutable(ROOT / 'logs' / args.run / 'objects', calculated)
        request = {'coordinator': args.name, 'epoch': epoch, 'result': ref}
        event(log, 'publish_attempt', **request)
        req = urllib.request.Request(f'http://127.0.0.1:{args.port}/result', encode(request),
                                     {'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                event(log, 'published', **json.load(response), message='записал результат')
        except urllib.error.HTTPError as exc:
            event(log, 'publication_rejected', status=exc.code, **json.load(exc))
            if exc.code != 409:
                raise
    finally:
        zk.stop()
        zk.close()


if __name__ == '__main__':
    main()
