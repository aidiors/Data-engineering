import argparse
import shutil
import tarfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from remote import ROOT, run


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--csv', type=Path, required=True)
    args = parser.parse_args()
    source = args.csv.resolve(strict=True)
    archive_path = ROOT / '.runtime/context.tar'
    repository = ROOT.parent
    files = ['hw3/config.json', 'hw3/frontend_lake/__init__.py', 'hw3/frontend_lake/common.py',
             'hw3/frontend_lake/validation.py', 'hw5/Dockerfile', 'hw5/Dockerfile.dockerignore',
             'hw5/requirements.txt', 'hw5/src/app.py']
    files += [path.relative_to(repository).as_posix() for path in (ROOT / 'manifests').glob('*.yaml')]
    with tarfile.open(archive_path, 'w') as archive:
        for filename in files:
            archive.add(repository / filename, arcname=filename)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = {'/input.csv': source, '/context.tar': archive_path}.get(self.path)
            if path is None:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header('Content-Length', str(path.stat().st_size))
            self.end_headers()
            with path.open('rb') as stream:
                shutil.copyfileobj(stream, self.wfile, 1048576)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = 'http://10.0.2.2:' + str(server.server_port)
    command = ('sudo mkdir -p /opt/hw5/input /opt/hw5/results /opt/hw5/project && '
               'sudo chown -R student:student /opt/hw5 && '
               f'curl -f {url}/context.tar -o /opt/hw5/context.tar && '
               'tar xf /opt/hw5/context.tar -C /opt/hw5/project && '
               f'curl -f {url}/input.csv -o /opt/hw5/input/it_vacancies_2024.csv && '
               'sha256sum /opt/hw5/input/it_vacancies_2024.csv && '
               'sudo chown 1000:1000 /opt/hw5/results && cd /opt/hw5/project && '
               'sudo docker build -t hw5-skills:1 -f hw5/Dockerfile .')
    try:
        status, output, error = run(command, ROOT / 'logs/image-build.txt')
        if status:
            raise RuntimeError(output[-2000:] + error)
    finally:
        server.shutdown()
        server.server_close()
    print('Input copied and calculation image built.')


if __name__ == '__main__':
    main()
