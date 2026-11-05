import argparse
import sys
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / '.runtime'


def connect():
    client = paramiko.SSHClient()
    hosts = RUNTIME / 'known_hosts'
    if hosts.exists():
        client.load_host_keys(str(hosts))
    else:
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect('127.0.0.1', port=2225, username='student', key_filename=str(RUNTIME / 'vm.key'),
                   look_for_keys=False, allow_agent=False, timeout=10, auth_timeout=15, banner_timeout=20)
    if not hosts.exists():
        client.save_host_keys(str(hosts))
    return client


def run(command, log=None, timeout=1800):
    client = connect()
    try:
        _, stdout, stderr = client.exec_command(command, timeout=timeout)
        stdout.channel.set_combine_stderr(True)
        blocks = []
        stream = Path(log).open('w', encoding='utf-8') if log else None
        if stream:
            stream.write('$ ' + command + '\n')
            stream.flush()
        while block := stdout.read(65536):
            text = block.decode('utf-8', errors='replace')
            blocks.append(text)
            if stream:
                stream.write(text)
                stream.flush()
        output = ''.join(blocks)
        error = ''
        status = stdout.channel.recv_exit_status()
        if stream:
            stream.close()
        return status, output, error
    finally:
        client.close()


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    parser.add_argument('command')
    parser.add_argument('--log')
    args = parser.parse_args()
    status, out, err = run(args.command, args.log)
    print(out, end='')
    print(err, end='')
    raise SystemExit(status)


if __name__ == '__main__':
    main()
