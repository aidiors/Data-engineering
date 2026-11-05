import argparse
import json
import socket
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

from kazoo.exceptions import BadVersionError

from .zk_common import ROOT, client, commit, encode, event, load_ref


def publish(zk, base, request, fencing):
    load_ref(request['result'])
    transaction = zk.transaction()
    if fencing:
        transaction.check(base + '/epoch', version=request['epoch'])

    transaction.set_data(base + '/result', encode(request), version=-1)
    transaction.create(base + '/publications/item-', encode(request), sequence=True)
    commit(transaction)
    return zk.get(base + '/result')[1].version


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', required=True)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--fencing', type=int, choices=(0, 1), default=int(os.environ.get('FENCING', '1')))
    args = parser.parse_args()
    base = '/hw4/' + args.run
    zk = client()
    log = ROOT / 'logs' / args.run / 'receiver.jsonl'

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            try:
                request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                version = publish(zk, base, request, args.fencing)
                event(log, 'published', coordinator=request['coordinator'], epoch=request['epoch'],
                      pointer_version=version, message='записал результат')
                self.send_response(200)
                response = {'pointer_version': version}
            except BadVersionError:
                event(log, 'rejected', coordinator=request['coordinator'], epoch=request['epoch'],
                      error='BadVersionError')
                self.send_response(409)
                response = {'error': 'BadVersionError'}
            except Exception as exc:
                event(log, 'error', error=repr(exc))
                self.send_response(500)
                response = {'error': type(exc).__name__}
            self.end_headers()
            self.wfile.write(encode(response))

        def log_message(self, *args):
            pass

    class ExclusiveHTTPServer(HTTPServer):
        allow_reuse_address = False

        def server_bind(self):
            if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            super().server_bind()

    server = ExclusiveHTTPServer(('127.0.0.1', args.port), Handler)
    event(log, 'ready', fencing=args.fencing, port=server.server_port)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        zk.stop()
        zk.close()


if __name__ == '__main__':
    main()
