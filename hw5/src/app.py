import argparse
import csv
import hashlib
import io
import json
import os
import sys
import time
from collections import Counter
from itertools import combinations
from pathlib import Path

import boto3
from botocore.config import Config

try:
    import resource
except ImportError:
    resource = None

repository = Path(__file__).resolve().parent.parent.parent
if (repository / 'hw3').is_dir():
    sys.path.insert(0, str(repository / 'hw3'))

from frontend_lake.common import selected, skills

csv.field_size_limit(2**31 - 1)
BUCKET = os.environ.get('S3_BUCKET', 'hh-lake')


def s3():
    return boto3.client('s3', endpoint_url=os.environ['S3_ENDPOINT'],
                        aws_access_key_id=os.environ['S3_ACCESS_KEY'],
                        aws_secret_access_key=os.environ['S3_SECRET_KEY'],
                        region_name='us-east-1',
                        config=Config(signature_version='s3v4', s3={'addressing_style': 'path'}, retries={'max_attempts': 3}))


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True).encode('utf-8')


def metrics():
    result = {'process_peak_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss if resource else 0}
    for name in ['memory.peak', 'memory.current', 'memory.max']:
        path = Path('/sys/fs/cgroup') / name
        if path.exists():
            result[name] = path.read_text().strip()
    return result


def result(counts, source_rows, ids):
    records = [{'skills': list(pair), 'frequency': frequency} for pair, frequency in sorted(counts.items())]
    canonical = sorted((2, row['skills'], row['frequency']) for row in records)
    return {'source_rows': source_rows, 'selected_rows': len(ids), 'selected_ids': sorted(ids),
            'sum_frequencies': sum(counts.values()), 'unique_pairs': len(counts), 'records': records,
            'top10': sorted(records, key=lambda row: (-row['frequency'], row['skills']))[:10],
            'sha256_pairs': hashlib.sha256(json.dumps(canonical, ensure_ascii=False).encode()).hexdigest()}


def count(stream, cap):
    counts = Counter()
    ids = []
    source_rows = 0
    for row in csv.DictReader(stream):
        source_rows += 1
        if selected(row):
            ids.append([row['source'], row['vacancy_id']])
            counts.update(combinations(skills(row['key_skills'], cap), 2))
    return result(counts, source_rows, ids)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['count', 'seed', 'reduce', 'hold'])
    parser.add_argument('--local', default='/input/it_vacancies_2024.csv')
    parser.add_argument('--cap', type=int, default=5)
    parser.add_argument('--parts', type=int, default=4)
    parser.add_argument('--s3-key')
    parser.add_argument('--indexed', action='store_true')
    parser.add_argument('--output-key', default='results/result.json')
    parser.add_argument('--seconds', type=int, default=900)
    args = parser.parse_args()
    started = time.monotonic()
    if args.action == 'hold':
        print(json.dumps({'state': 'holding', 'seconds': args.seconds}), flush=True)
        time.sleep(args.seconds)
        return
    if args.action == 'seed':
        client = s3()
        if BUCKET not in [bucket['Name'] for bucket in client.list_buckets()['Buckets']]:
            client.create_bucket(Bucket=BUCKET)
        client.upload_file(args.local, BUCKET, 'raw/it_vacancies_2024.csv')
        paths = [Path('/tmp') / f'part-{index:03d}.csv' for index in range(args.parts)]
        streams = [path.open('w', encoding='utf-8', newline='') for path in paths]
        try:
            with open(args.local, encoding='utf-8-sig', newline='') as source:
                reader = csv.DictReader(source)
                writers = [csv.DictWriter(stream, fieldnames=reader.fieldnames) for stream in streams]
                for writer in writers:
                    writer.writeheader()
                rows = 0
                for index, row in enumerate(reader):
                    writers[index % args.parts].writerow(row)
                    rows += 1
        finally:
            for stream in streams:
                stream.close()
        for index, path in enumerate(paths):
            client.upload_file(str(path), BUCKET, f'input/part-{index:03d}.csv')
        print(json.dumps({'action': 'seed', 'source_rows': rows, 'parts': args.parts, 'seconds': time.monotonic() - started}), flush=True)
        return
    if args.action == 'reduce':
        client = s3()
        counts = Counter()
        source_rows = 0
        ids = []
        for index in range(args.parts):
            partial = json.loads(client.get_object(Bucket=BUCKET, Key=f'partials/part-{index:03d}.json')['Body'].read())
            counts.update({tuple(row['skills']): row['frequency'] for row in partial['records']})
            source_rows += partial['source_rows']
            ids.extend(partial['selected_ids'])
        assert len({tuple(row) for row in ids}) == len(ids)
        calculated = result(counts, source_rows, ids)
    else:
        key = args.s3_key
        if args.indexed:
            index = int(os.environ['JOB_COMPLETION_INDEX'])
            key = f'input/part-{index:03d}.csv'
            args.output_key = f'partials/part-{index:03d}.json'
        if key:
            response = s3().get_object(Bucket=BUCKET, Key=key)
            with io.TextIOWrapper(io.BufferedReader(response['Body'], 1048576), encoding='utf-8-sig', newline='') as stream:
                calculated = count(stream, args.cap)
        else:
            with open(args.local, encoding='utf-8-sig', newline='') as stream:
                calculated = count(stream, args.cap)
    calculated['elapsed_seconds'] = time.monotonic() - started
    calculated['metrics'] = metrics()
    if 'S3_ENDPOINT' in os.environ:
        s3().put_object(Bucket=BUCKET, Key=args.output_key, Body=encode(calculated), ContentType='application/json')
    if os.environ.get('RESULT_DIR'):
        path = Path(os.environ['RESULT_DIR']) / (os.environ.get('JOB_NAME', 'result') + '.json')
        path.write_bytes(encode(calculated))
    print(json.dumps({key: value for key, value in calculated.items() if key not in ['records', 'selected_ids']}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
