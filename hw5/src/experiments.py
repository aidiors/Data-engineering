import argparse
import json
import math
import secrets
import time
from datetime import datetime
from pathlib import Path

import yaml

from remote import ROOT, connect, run

LOGS = ROOT / 'logs'
GUEST = '/opt/hw5/project/hw5'
K = 'sudo k3s kubectl'


def save(name, value):
    (LOGS / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def execute(command, name, expected=0, timeout=1800):
    status, output, error = run(command, LOGS / name, timeout)
    if status != expected:
        raise RuntimeError(f'{name}: exit={status}\n{output[-4000:]}\n{error[-1000:]}')
    return output


def upload(path, destination):
    client = connect()
    try:
        with client.open_sftp() as sftp:
            sftp.put(str(path), destination)
    finally:
        client.close()


def fetch(source, destination):
    client = connect()
    try:
        with client.open_sftp() as sftp:
            sftp.get(source, str(destination))
    finally:
        client.close()


def apply(filename):
    path = ROOT / 'manifests' / filename
    upload(path, GUEST + '/manifests/' + filename)
    execute(K + ' apply -f ' + GUEST + '/manifests/' + filename, 'apply-' + filename + '.txt')


def snapshot(arguments, filename):
    output = execute(K + ' ' + arguments + ' -o json', filename + '.command.txt')
    data = json.loads(output)
    save(filename + '.json', data)
    return data


def job(name, failure=False):
    condition = "jsonpath='{.status.failed}'=1" if failure else 'condition=complete'
    execute(K + ' -n hw5 wait --for=' + condition + ' job/' + name + ' --timeout=1200s', name + '-wait.txt', timeout=1300)
    pods = snapshot('-n hw5 get pods -l batch.kubernetes.io/job-name=' + name, name + '-pods')
    snapshot('-n hw5 get job ' + name, name + '-job')
    status, output, error = run(K + ' -n hw5 logs job/' + name + ' --all-containers=true', LOGS / (name + '.log'))
    if not failure and status:
        raise RuntimeError(error + output)
    if len(pods['items']) > 1:
        for pod in pods['items']:
            pod_name = pod['metadata']['name']
            execute(K + ' -n hw5 logs pod/' + pod_name + ' --all-containers=true', pod_name + '.log')
    return pods


def memory():
    apply('00-namespaces.yaml')
    apply('10-memory-profile.yaml')
    job('memory-profile')
    fetch('/opt/hw5/results/memory-profile.json', LOGS / 'memory-profile-result.json')
    result = json.loads((LOGS / 'memory-profile-result.json').read_text(encoding='utf-8'))
    peak = max(result['metrics']['process_peak_kib'] * 1024, int(result['metrics'].get('memory.peak', 0)))
    limit_mi = math.ceil((peak / 1048576 * 1.3 + 16) / 16) * 16
    request_mi = max(64, math.ceil(peak / 1048576 / 16) * 16)
    for filename in ['12-memory-tuned.yaml', '40-parallel.yaml', '41-reduce.yaml']:
        path = ROOT / 'manifests' / filename
        manifest = yaml.safe_load(path.read_text(encoding='utf-8'))
        resources = manifest['spec']['template']['spec']['containers'][0]['resources']
        resources['limits']['memory'] = str(limit_mi) + 'Mi'
        resources['requests']['memory'] = str(request_mi) + 'Mi'
        path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding='utf-8')
    apply('11-memory-oom.yaml')
    oom_pods = job('memory-oom', failure=True)
    terminated = [container['state'].get('terminated', {}) for pod in oom_pods['items'] for container in pod['status'].get('containerStatuses', [])]
    assert any(state.get('reason') == 'OOMKilled' and state.get('exitCode') == 137 for state in terminated), terminated
    apply('12-memory-tuned.yaml')
    job('memory-tuned')
    fetch('/opt/hw5/results/memory-tuned.json', LOGS / 'memory-tuned-result.json')
    tuned = json.loads((LOGS / 'memory-tuned-result.json').read_text(encoding='utf-8'))
    assert result['records'] == tuned['records']
    save('memory-summary.json', {'profile_limit_mi': 256, 'oom_limit_mi': 16,
                                'measured_peak_bytes': peak, 'tuned_limit_mi': limit_mi,
                                'tuned_request_mi': request_mi, 'tuned_peak': tuned['metrics'],
                                'oom_reason': 'OOMKilled', 'oom_exit_code': 137})
    print('Memory profiling, OOMKilled and tuned run verified.', flush=True)


def storage():
    credentials_file = ROOT / '.runtime/s3-credentials.json'
    if not credentials_file.exists():
        credentials_file.write_text(json.dumps({'S3_ACCESS_KEY': 'hw5-student', 'S3_SECRET_KEY': secrets.token_urlsafe(32)}), encoding='utf-8')
    values = json.loads(credentials_file.read_text(encoding='utf-8'))
    manifest = {'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': 's3-credentials', 'namespace': 'hw5'}, 'type': 'Opaque', 'stringData': values}
    secret_path = ROOT / '.runtime/secret.yaml'
    secret_path.write_text(yaml.safe_dump(manifest), encoding='utf-8')
    upload(secret_path, '/opt/hw5/secret.yaml')
    execute('chmod 600 /opt/hw5/secret.yaml && ' + K + ' apply -f /opt/hw5/secret.yaml', 'secret-created.txt')
    apply('20-rustfs.yaml')
    execute(K + ' -n hw5 rollout status deployment/rustfs --timeout=600s', 'rustfs-ready.txt', timeout=650)
    snapshot('-n hw5 get deployment rustfs', 'rustfs-deployment')
    snapshot('-n hw5 get pvc rustfs-data', 'rustfs-pvc')
    snapshot('-n hw5 get service rustfs', 'rustfs-service')
    apply('30-seed.yaml')
    job('seed-s3')
    print('RustFS and partition upload completed.', flush=True)


def parallel():
    apply('40-parallel.yaml')
    job('pairs-parallel')
    apply('41-reduce.yaml')
    job('pairs-reduce')
    print('Parallel calculation and reduction completed.', flush=True)


def wait_pod(name, predicate, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status, output, error = run(K + ' -n hw5 get pod ' + name + ' -o json')
        if not status:
            data = json.loads(output)
            if predicate(data):
                return data
        time.sleep(3)
    raise TimeoutError(name)


def scheduling():
    apply('50-priorities.yaml')
    apply('51-low.yaml')
    low = wait_pod('low-priority', lambda pod: pod['status']['phase'] == 'Running')
    save('priority-before.json', low)
    apply('52-cpu-waiting.yaml')
    waiting = wait_pod('cpu-waiting', lambda pod: any(condition.get('reason') == 'Unschedulable' for condition in pod['status'].get('conditions', [])))
    message = next(condition['message'] for condition in waiting['status']['conditions'] if condition.get('reason') == 'Unschedulable')
    assert 'Insufficient cpu' in message, message
    save('cpu-pending.json', waiting)
    execute(K + ' -n hw5 describe pod cpu-waiting', 'cpu-pending-describe.txt')
    execute(K + ' -n hw5 delete pod cpu-waiting --wait=true', 'cpu-pending-cleanup.txt')
    apply('53-high.yaml')
    high = wait_pod('high-priority', lambda pod: pod['status']['phase'] == 'Running')
    save('priority-after.json', high)
    events = snapshot('-n hw5 get events', 'priority-events')
    preempted = [event for event in events['items'] if event.get('reason') == 'Preempted' and event.get('involvedObject', {}).get('uid') == low['metadata']['uid']]
    assert preempted, 'No preemption event for the low priority pod'
    save('scheduling-summary.json', {'pending_reason': 'Insufficient cpu', 'low_uid': low['metadata']['uid'],
                                    'high_uid': high['metadata']['uid'], 'low_priority': low['spec']['priority'],
                                    'high_priority': high['spec']['priority'], 'preemption_event': preempted})
    execute(K + ' -n hw5 delete pod high-priority --wait=true', 'priority-cleanup.txt')
    print('CPU Pending and real scheduler preemption verified.', flush=True)


def quota():
    apply('60-quota.yaml')
    apply('61-quota-first.yaml')
    execute(K + ' -n hw5-quota wait --for=condition=Ready pod/quota-first --timeout=180s', 'quota-first-ready.txt')
    upload(ROOT / 'manifests/62-quota-rejected.yaml', GUEST + '/manifests/62-quota-rejected.yaml')
    status, output, error = run(K + ' create -f ' + GUEST + '/manifests/62-quota-rejected.yaml', LOGS / 'quota-rejection.txt')
    assert status != 0 and 'exceeded quota' in output + error, output + error
    data = snapshot('-n hw5-quota get resourcequota student-quota', 'quota-status')
    save('quota-summary.json', {'rejected': True, 'error': (output + error).strip(), 'used': data['status']['used'], 'hard': data['status']['hard']})
    execute(K + ' -n hw5-quota delete pod quota-first --wait=true', 'quota-cleanup.txt')
    print('Namespace quota admission rejection verified.', flush=True)


def verify():
    import boto3
    from botocore.config import Config
    values = json.loads((ROOT / '.runtime/s3-credentials.json').read_text(encoding='utf-8'))
    client = boto3.client('s3', endpoint_url='http://127.0.0.1:9005', aws_access_key_id=values['S3_ACCESS_KEY'],
                          aws_secret_access_key=values['S3_SECRET_KEY'], region_name='us-east-1',
                          config=Config(signature_version='s3v4', s3={'addressing_style': 'path'}))
    result = json.loads(client.get_object(Bucket='hh-lake', Key='results/result.json')['Body'].read())
    baseline = json.loads((ROOT.parent / 'hw3/output/counts/mr_5.json').read_text(encoding='utf-8'))
    records = [{'skills': row['skills'], 'frequency': row['frequency']} for row in baseline['records'] if row['k'] == 2]
    top = sorted(records, key=lambda row: (-row['frequency'], row['skills']))[:10]
    assert result['records'] == records and result['top10'] == top
    assert result['selected_ids'] == baseline['selected_ids']
    assert result['source_rows'] == baseline['source_rows']
    for name in ['memory-profile', 'memory-tuned']:
        local = json.loads((LOGS / (name + '-result.json')).read_text(encoding='utf-8'))
        assert local['records'] == records and local['top10'] == top
    pods = json.loads((LOGS / 'pairs-parallel-pods.json').read_text(encoding='utf-8'))['items']
    intervals = []
    for pod in pods:
        state = pod['status']['containerStatuses'][0]['state']['terminated']
        assert state['exitCode'] == 0
        intervals.append({'pod': pod['metadata']['name'], 'started_at': state['startedAt'], 'finished_at': state['finishedAt']})
    changes = []
    for interval in intervals:
        changes.extend([(datetime.fromisoformat(interval['started_at'].replace('Z', '+00:00')), 1),
                        (datetime.fromisoformat(interval['finished_at'].replace('Z', '+00:00')), -1)])
    active = maximum = 0
    for _, change in sorted(changes):
        active += change
        maximum = max(maximum, active)
    assert len(intervals) == 4 and maximum == 2
    save('parallelism.json', {'completed_pods': len(intervals), 'maximum_concurrent_pods': maximum, 'intervals': intervals})
    save('parallel-result.json', result)
    for index in range(4):
        partial = json.loads(client.get_object(Bucket='hh-lake', Key=f'partials/part-{index:03d}.json')['Body'].read())
        save(f'part-{index}-result.json', partial)
    save('top10.json', top)
    save('verification.json', {'equal_to_hw3': True, 'all_pair_frequencies_equal': True,
                              'all_ids_equal': True, 'top10_equal': True, 'source_rows': result['source_rows'],
                              'selected_rows': result['selected_rows'], 'unique_pairs': result['unique_pairs'],
                              'sum_frequencies': result['sum_frequencies'], 'sha256_pairs': result['sha256_pairs']})
    objects = client.list_objects_v2(Bucket='hh-lake')['Contents']
    save('s3-objects.json', [{'key': row['Key'], 'bytes': row['Size']} for row in objects])
    print('Every pair frequency, every selected ID and top 10 equal HW3.', flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['memory', 'storage', 'parallel', 'scheduling', 'quota', 'verify', 'all'])
    args = parser.parse_args()
    LOGS.mkdir(exist_ok=True)
    stages = [memory, storage, parallel, scheduling, quota, verify] if args.stage == 'all' else [globals()[args.stage]]
    for stage in stages:
        stage()
    snapshot('get nodes', 'nodes')


if __name__ == '__main__':
    main()
