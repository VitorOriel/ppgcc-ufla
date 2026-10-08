import requests
import yaml
import os
import json
import sys
import time

API_URL = "http://localhost:3000/api/v1/smelly"
RULE = 'K8S_SEC_CAPABILITIES_VALUE'
PROGRESS_EVERY = 2000
DOCUMENT_SEPARATOR = '---'
WORKLOAD_KINDS = ['Pod', 'Job', 'CronJob', 'ReplicaSet', 'Deployment', 'StatefulSet', 'DaemonSet']

total_files = 0
valid_files = 0
flagged_workloads = 0
rule_detections = 0
false_positives = 0
detections_by_kind = {}
false_positive_details = []

session = requests.Session()

def collect_files(directory: str) -> list[str]:
    paths = []
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith('.yaml') or file.endswith('.yml'):
                paths.append(os.path.join(root, file))
    paths.sort()
    return paths

def send_file(file_path: str) -> requests.Response:
    with open(file_path, 'r', encoding='utf-8', errors='replace') as file:
        body = {
            'FileName': os.path.basename(file_path),
            'YamlToValidate': file.read(),
        }
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

def decode_workloads(file_path: str) -> list[dict]:
    workloads = []
    with open(file_path, 'r', encoding='utf-8', errors='replace') as file:
        content = file.read()
    for chunk in content.split(DOCUMENT_SEPARATOR):
        if len(chunk) == 0:
            continue
        try:
            document = yaml.safe_load(chunk)
        except yaml.YAMLError:
            continue
        if not isinstance(document, dict):
            continue
        if document.get('kind') in WORKLOAD_KINDS:
            workloads.append(document)
    return workloads

def get_drop_list(container: dict) -> list:
    if not isinstance(container, dict):
        return None
    security_context = container.get('securityContext')
    if not isinstance(security_context, dict):
        return None
    capabilities = security_context.get('capabilities')
    if not isinstance(capabilities, dict):
        return None
    drop = capabilities.get('drop')
    if not isinstance(drop, list):
        return []
    return drop

def is_positional_smell(drop: list) -> bool:
    if len(drop) == 0:
        return True
    return str(drop[0]).upper() != 'ALL'

def declares_all(drop: list) -> bool:
    for capability in drop:
        if str(capability).upper() == 'ALL':
            return True
    return False

def reclassify(file_path: str, relative_path: str) -> dict:
    flagged = 0
    details = []
    for document in decode_workloads(file_path):
        containers = get_pod_spec(document).get('containers')
        if not isinstance(containers, list):
            continue
        workload_flagged = False
        for container in containers:
            drop = get_drop_list(container)
            if drop is None or not is_positional_smell(drop):
                continue
            workload_flagged = True
            if declares_all(drop):
                details.append({
                    'file': relative_path,
                    'kind': document.get('kind'),
                    'workload': get_nested_dict(document, 'metadata').get('name'),
                    'container': container.get('name'),
                    'drop': drop,
                })
        if workload_flagged:
            flagged += 1
    return {'flagged_workloads': flagged, 'details': details}

def count_api_detections(result: dict) -> dict:
    counted = 0
    by_kind = {}
    for kind, smells in dict(result['data']).items():
        for smell in list(smells or []):
            if smell['rule'] != RULE:
                continue
            counted += 1
            by_kind[kind] = by_kind.get(kind, 0) + 1
    return {'detections': counted, 'by_kind': by_kind}

def examine(file_path: str, relative_path: str) -> dict:
    response = send_file(file_path)
    if not response.ok:
        return {'valid': False}
    return {'valid': True,
            'api': count_api_detections(response.json()),
            'local': reclassify(file_path, relative_path)}

def process_yaml_files(directory: str) -> None:
    global total_files
    global valid_files
    global rule_detections
    global flagged_workloads
    global false_positives
    paths = collect_files(directory)
    population = len(paths)
    print(f"{population} files to process", file=sys.stderr, flush=True)
    for index, file_path in enumerate(paths, start=1):
        total_files += 1
        if index % PROGRESS_EVERY == 0 or index == population:
            print(f"progress {index}/{population} ({100*index/population:.1f}%) "
                  f"valid={valid_files} detections={rule_detections} fp={false_positives}",
                  file=sys.stderr, flush=True)
        outcome = examine(file_path, os.path.relpath(file_path, directory))
        if not outcome['valid']:
            continue
        valid_files += 1
        rule_detections += outcome['api']['detections']
        for kind, count in outcome['api']['by_kind'].items():
            detections_by_kind[kind] = detections_by_kind.get(kind, 0) + count
        flagged_workloads += outcome['local']['flagged_workloads']
        false_positives += len(outcome['local']['details'])
        false_positive_details.extend(outcome['local']['details'])

process_yaml_files(sys.argv[1])
print(json.dumps({
    'total_files': total_files,
    'valid_files': valid_files,
    'rule': RULE,
    'rule_detections': rule_detections,
    'flagged_workloads': flagged_workloads,
    'false_positives': false_positives,
    'false_positive_rate': false_positives/rule_detections if rule_detections else 0,
    'detections_by_kind': detections_by_kind,
    'false_positive_details': false_positive_details,
}, indent=4))
