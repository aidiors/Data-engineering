import argparse
import json
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

import psutil

from .zk_common import ROOT, save

RUNTIME = ROOT / '.runtime'
CREATE_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def wait_for(predicate, seconds=30):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.1)
    raise TimeoutError(f'Condition not met in {seconds} seconds')


def terminate(pid):
    try:
        parent = psutil.Process(pid)
        children = parent.children(recursive=True)
        for process in reversed(children):
            try:
                process.kill()
            except psutil.NoSuchProcess:
                pass
        parent.kill()
        psutil.wait_procs(children + [parent], timeout=5)
    except psutil.NoSuchProcess:
        pass


class Ensemble:
    def __init__(self):
        self.config = json.loads((RUNTIME / 'environment.json').read_text(encoding='utf-8-sig'))

    def setup(self):
        distribution = Path(self.config['distribution'])
        for number in (1, 2, 3):
            directory = RUNTIME / f'server{number}'
            if not directory.exists():
                shutil.copytree(distribution, directory)
            data = directory / 'data'
            if not data.exists():
                data.mkdir()
                (data / 'myid').write_text(str(number), encoding='ascii')
                (data / 'initialize').touch()
            config = ROOT / 'conf' / f'server{number}' / 'zoo.cfg'
            shutil.copyfile(config, directory / 'conf/zoo.cfg')

    def start(self, number):
        logdir = ROOT / 'logs/ensemble'
        logdir.mkdir(parents=True, exist_ok=True)
        environment = {**os.environ, 'JAVA_HOME': self.config['java_home']}
        environment['JDK_JAVA_OPTIONS'] = '-Xms64m -Xmx256m -Dzookeeper.nio.numSelectorThreads=1 -Dzookeeper.nio.numWorkerThreads=4'
        with (logdir / f'server{number}.console.log').open('ab') as output:
            process = subprocess.Popen(
                ['cmd.exe', '/d', '/c', str(RUNTIME / f'server{number}/bin/zkServer.cmd')],
                cwd=ROOT, env=environment, stdout=output, stderr=subprocess.STDOUT,
                creationflags=CREATE_NO_WINDOW)
        (RUNTIME / f'server{number}.pid').write_text(str(process.pid))
        return process.pid

    def stop(self, number):
        path = RUNTIME / f'server{number}.pid'
        if path.exists():
            pid = int(path.read_text())
            try:
                process = psutil.Process(pid)
                if any('zkServer.cmd' in part for part in process.cmdline()):
                    terminate(pid)
            except psutil.NoSuchProcess:
                pass
            path.unlink()

    def status(self, number):
        try:
            with socket.create_connection(('127.0.0.1', 2180 + number), timeout=1) as connection:
                connection.settimeout(2)
                connection.sendall(b'srvr')
                chunks = []
                while block := connection.recv(65536):
                    chunks.append(block)
                return b''.join(chunks).decode('utf-8', errors='replace')
        except OSError as exc:
            return type(exc).__name__ + ': ' + str(exc)

    def ready(self):
        statuses = [self.status(i) for i in (1, 2, 3)]
        return statuses if sum('Mode: leader' in s for s in statuses) == 1 and sum('Mode: follower' in s for s in statuses) == 2 else None

    def cli(self, commands, output):
        environment = {**os.environ, 'JAVA_HOME': self.config['java_home']}
        directory = RUNTIME / 'server1'
        with Path(output).open('wb') as stream:
            process = subprocess.Popen(
                ['cmd.exe', '/d', '/c', str(directory / 'bin/zkCli.cmd'), '-server', '127.0.0.1:2181'],
                cwd=ROOT, env=environment, stdin=subprocess.PIPE, stdout=stream,
                stderr=subprocess.STDOUT, creationflags=CREATE_NO_WINDOW)
        time.sleep(2)
        process.stdin.write(commands.encode())
        process.stdin.flush()
        return process


def main():
    p = argparse.ArgumentParser()
    p.add_argument('action', choices=('setup', 'start', 'stop', 'status'))
    p.add_argument('number', type=int, nargs='?', choices=(1, 2, 3))
    args = p.parse_args()
    ensemble = Ensemble()
    if args.action == 'setup':
        ensemble.setup()
    else:
        for number in [args.number] if args.number else (1, 2, 3):
            print(number, getattr(ensemble, args.action)(number))


if __name__ == '__main__':
    main()
