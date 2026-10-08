import requests
import yaml
import os
import json
import sys
import time
import hashlib

API_URL = "http://localhost:3000/api/v1/smelly"
PROGRESS_EVERY = 2000
DOCUMENT_SEPARATOR = '---'
WORKLOAD_KINDS = ['Pod', 'Job', 'CronJob', 'ReplicaSet', 'Deployment', 'StatefulSet', 'DaemonSet']
TOP_DUPLICATES = 10

session = requests.Session()

def collect_files(directory: str) -> list[str]:
    paths = []
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith('.yaml') or file.endswith('.yml'):
                paths.append(os.path.join(root, file))
    paths.sort()
    return paths

def read_file(file_path: str) -> str:
    with open(file_path, 'r', encoding='utf-8', errors='replace') as file:
        return file.read()

def send_file(file_path: str, content: str) -> requests.Response:
    body = {'FileName': os.path.basename(file_path), 'YamlToValidate': content}
    last_error = None
    for attempt in range(5):
        try:
            return session.post(API_URL, headers={'Content-Type': "application/json"}, json=body, timeout=600)
        except requests.exceptions.RequestException as error:
            last_error = error
            print(f"retry {attempt+1}/5 on {file_path}: {error}", file=sys.stderr, flush=True)
            time.sleep(2 ** attempt)
    raise SystemExit(f"API unreachable after 5 attempts on {file_path}: {last_error}")

def get_nested_dict(value: dict, key: str) -> dict:
    if not isinstance(value, dict):
        return {}
    nested = value.get(key)
    if not isinstance(nested, dict):
        return {}
    return nested

def get_pod_spec(document: dict) -> dict:
    spec = get_nested_dict(document, 'spec')
    if document.get('kind') == 'Pod':
        return spec
    if document.get('kind') == 'CronJob':
        job_spec = get_nested_dict(get_nested_dict(spec, 'jobTemplate'), 'spec')
        return get_nested_dict(get_nested_dict(job_spec, 'template'), 'spec')
    return get_nested_dict(get_nested_dict(spec, 'template'), 'spec')

def normalize(content: str) -> str:
    lines = [line.rstrip() for line in content.splitlines()]
    return '\n'.join([line for line in lines if line])

def parse_documents(content: str) -> list:
    documents = []
    for chunk in content.split(DOCUMENT_SEPARATOR):
        if len(chunk) == 0:
            continue
        try:
            documents.append(yaml.safe_load(chunk))
        except yaml.YAMLError:
            documents.append(normalize(chunk))
    return documents

def digest(value) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(',', ':'), default=str)
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()

def describe_workloads(documents: list) -> list[dict]:
    described = []
    for document in documents:
        if not isinstance(document, dict):
            continue
        if document.get('kind') not in WORKLOAD_KINDS:
            continue
        described.append({
            'digest': digest([document.get('kind'), get_pod_spec(document)]),
            'kind': document.get('kind'),
            'name': get_nested_dict(document, 'metadata').get('name'),
        })
    return described

def new_tally() -> dict:
    return {'counter': {}, 'examples': {}}

def add(tally: dict, key: str, example: str) -> None:
    tally['counter'][key] = tally['counter'].get(key, 0) + 1
    tally['examples'].setdefault(key, example)

def total(tally: dict) -> int:
    return sum(tally['counter'].values())

def distinct(tally: dict) -> int:
    return len(tally['counter'])

def rank(tally: dict) -> list[dict]:
    ordered = sorted(tally['counter'].items(), key=lambda item: (-item[1], item[0]))
    return [{'copies': count, 'example': tally['examples'][key]}
            for key, count in ordered[:TOP_DUPLICATES] if count > 1]

def rate(tally: dict) -> float:
    counted = total(tally)
    return (counted - distinct(tally))/counted if counted else 0

def examine(file_path: str) -> dict:
    content = read_file(file_path)
    response = send_file(file_path, content)
    if not response.ok:
        return {'valid': False}
    documents = parse_documents(content)
    return {'valid': True,
            'digest': digest(documents),
            'workloads': describe_workloads(documents)}

def process(directory: str) -> dict:
    paths = collect_files(directory)
    population = len(paths)
    print(f"{directory}: {population} files to process", file=sys.stderr, flush=True)
    total_files = 0
    files = new_tally()
    workloads = new_tally()
    for index, file_path in enumerate(paths, start=1):
        total_files += 1
        if index % PROGRESS_EVERY == 0 or index == population:
            print(f"progress {index}/{population} ({100*index/population:.1f}%) "
                  f"valid={total(files)} workloads={total(workloads)} distinct={distinct(workloads)}",
                  file=sys.stderr, flush=True)
        outcome = examine(file_path)
        if not outcome['valid']:
            continue
        relative_path = os.path.relpath(file_path, directory)
        add(files, outcome['digest'], relative_path)
        for workload in outcome['workloads']:
            add(workloads, workload['digest'], f"{workload['kind']} {workload['name']} in {relative_path}")
    return {
        'root': directory,
        'total_files': total_files,
        'valid_files': total(files),
        'distinct_files': distinct(files),
        'duplicate_files': total(files) - distinct(files),
        'file_duplication_rate': rate(files),
        'workloads': total(workloads),
        'distinct_workloads': distinct(workloads),
        'duplicate_workloads': total(workloads) - distinct(workloads),
        'workload_duplication_rate': rate(workloads),
        'most_duplicated_files': rank(files),
        'most_duplicated_workloads': rank(workloads),
        'file_digests': set(files['counter']),
        'workload_digests': set(workloads['counter']),
    }

reports = [process(directory) for directory in sys.argv[1:]]

overlap = []
for i in range(len(reports)):
    for j in range(i + 1, len(reports)):
        first, second = reports[i], reports[j]
        overlap.append({
            'datasets': [first['root'], second['root']],
            'shared_files': len(first['file_digests'] & second['file_digests']),
            'shared_workloads': len(first['workload_digests'] & second['workload_digests']),
        })

for report in reports:
    del report['file_digests']
    del report['workload_digests']

print(json.dumps({'datasets': reports, 'overlap': overlap}, indent=4))
