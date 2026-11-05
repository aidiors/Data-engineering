import argparse
import io
import socket
import subprocess
import time
from pathlib import Path

import pycdlib
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from remote import ROOT, run

RUNTIME = ROOT / '.runtime'


def seed():
    if (RUNTIME / 'seed.iso').exists():
        return
    key_path = RUNTIME / 'vm.key'
    if key_path.exists():
        key = serialization.load_ssh_private_key(key_path.read_bytes(), password=None)
    else:
        key = Ed25519PrivateKey.generate()
        key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH, serialization.NoEncryption()))
    public = key.public_key().public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH).decode()
    config = {'hostname': 'hw5-node', 'manage_etc_hosts': True,
              'users': [{'name': 'student', 'groups': ['sudo', 'docker'], 'shell': '/bin/bash',
                         'sudo': 'ALL=(ALL) NOPASSWD:ALL', 'ssh_authorized_keys': [public]}],
              'ssh_pwauth': False, 'disable_root': True, 'package_update': True,
              'packages': ['curl', 'ca-certificates', 'docker.io', 'python3', 'jq', 'time'],
              'runcmd': [['sh', '-c', 'systemctl enable --now docker'],
                        ['sh', '-c', 'curl -sfL https://get.k3s.io -o /tmp/install-k3s.sh && INSTALL_K3S_VERSION=v1.37.2+k3s1 sh /tmp/install-k3s.sh server --docker --disable traefik --disable servicelb --node-name hw5-node --tls-san 127.0.0.1']]}
    iso = pycdlib.PyCdlib()
    iso.new(interchange_level=3, joliet=3, vol_ident='CIDATA', rock_ridge='1.09')
    for filename, data in [('user-data', ('#cloud-config\n' + yaml.safe_dump(config, sort_keys=False)).encode()),
                           ('meta-data', b'instance-id: hw5-local-001\nlocal-hostname: hw5-node\n')]:
        iso_path = '/USERDATA.;1' if filename == 'user-data' else '/METADATA.;1'
        iso.add_fp(io.BytesIO(data), len(data), iso_path=iso_path, rr_name=filename, joliet_path='/' + filename)
    iso.write(str(RUNTIME / 'seed.iso'))
    iso.close()


def listening():
    try:
        with socket.create_connection(('127.0.0.1', 2225), timeout=2):
            return True
    except OSError:
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['start', 'stop', 'status'])
    args = parser.parse_args()
    if args.action == 'stop':
        run('sudo systemd-run --on-active=2s /usr/sbin/poweroff', timeout=15)
        return
    if args.action == 'start' and not listening():
        seed()
        command = [str(RUNTIME / 'qemu/qemu-system-x86_64.exe'), '-machine', 'q35,accel=tcg', '-cpu', 'max',
                   '-smp', '2', '-m', '8192', '-device', 'virtio-rng-pci',
                   '-drive', 'file=' + str(RUNTIME / 'debian.qcow2') + ',if=virtio,format=qcow2',
                   '-drive', 'file=' + str(RUNTIME / 'seed.iso') + ',media=cdrom,readonly=on',
                   '-netdev', 'user,id=n0,hostfwd=tcp:127.0.0.1:2225-:22,hostfwd=tcp:127.0.0.1:6445-:6443,hostfwd=tcp:127.0.0.1:9005-:30900',
                   '-device', 'virtio-net-pci,netdev=n0', '-display', 'none',
                   '-serial', 'file:' + str(RUNTIME / 'serial.log'), '-monitor', 'none']
        with (RUNTIME / 'qemu.stdout.log').open('ab') as out, (RUNTIME / 'qemu.stderr.log').open('ab') as err:
            process = subprocess.Popen(command, stdout=out, stderr=err, creationflags=subprocess.CREATE_NO_WINDOW)
        (RUNTIME / 'vm.pid').write_text(str(process.pid))
    deadline = time.monotonic() + (900 if args.action == 'start' else 20)
    while time.monotonic() < deadline:
        try:
            status, out, error = run('sudo k3s kubectl get nodes -o wide', timeout=20)
            if not status and ' Ready ' in out:
                print(out)
                return
        except Exception:
            pass
        time.sleep(3)
    raise TimeoutError('Kubernetes is not ready')


if __name__ == '__main__':
    main()
