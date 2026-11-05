import hashlib
import json
import logging
import os
import time
from pathlib import Path

from kazoo.client import KazooClient

ROOT = Path(__file__).resolve().parents[1]
HOSTS = os.environ.get('ZK_HOSTS', '127.0.0.1:2181,127.0.0.1:2182,127.0.0.1:2183')


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True).encode('utf-8')


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_bytes(encode(value))
    temporary.replace(path)


def immutable(directory, value):
    payload = encode(value)
    digest = hashlib.sha256(payload).hexdigest()
    path = Path(directory) / (digest + '.json')
    if not path.exists():
        save(path, value)
    return {'file': str(path.relative_to(ROOT)), 'sha256': digest}


def load_ref(ref):
    path = (ROOT / ref['file']).resolve()
    if not path.is_relative_to(ROOT.resolve()):
        raise ValueError('Reference outside homework directory')
    payload = path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != ref['sha256']:
        raise ValueError('Corrupt immutable object')
    return json.loads(payload)


def client(timeout=10):
    logging.getLogger('kazoo').setLevel(logging.ERROR)
    zk = KazooClient(hosts=HOSTS, timeout=timeout, read_only=False)
    zk.start(timeout=15)
    return zk


def commit(transaction):
    results = transaction.commit()

    for result in results:
        if isinstance(result, Exception) and type(result).__name__ != 'RolledBackError':
            raise result
    for result in results:
        if isinstance(result, Exception):
            raise result
    return results


def event(log_path, kind, **fields):
    row = {'time': time.time(), 'monotonic_ns': time.monotonic_ns(),
           'event': kind, **fields}
    line = json.dumps(row, ensure_ascii=False)
    with Path(log_path).open('a', encoding='utf-8') as stream:
        stream.write(line + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    print(line, flush=True)
    return row
