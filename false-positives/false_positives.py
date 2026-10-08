import requests
import yaml
import os
import re
import json
import sys

API_URL = "http://localhost:3000/api/v1/smelly"
RULE = 'K8S_SEC_CAPABILITIES_VALUE'
WORKLOAD_KINDS = ['Pod', 'Job', 'CronJob', 'ReplicaSet', 'Deployment', 'StatefulSet', 'DaemonSet']
DOCUMENT_SEPARATOR = re.compile(r'^---\s*$', re.MULTILINE)

total_files = 0
valid_files = 0
flagged_workloads = 0
rule_detections = 0
reclassified_detections = 0
false_positives = 0
detections_by_kind = {}
false_positive_details = []
unresolved_workloads = []

session = requests.Session()

def send_file(file_path: str) -> requests.Response:
    with open(file_path, 'r', encoding='utf-8', errors='replace') as file:
        body = {
            'FileName': os.path.basename(file_path),
            'YamlToValidate': file.read(),
        }
    return session.post(API_URL, headers={'Content-Type': "application/json"}, json=body, timeout=600)

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

def read_workloads(file_path: str) -> list[dict]:
    workloads = []
    with open(file_path, 'r', encoding='utf-8', errors='replace') as file:
        content = file.read()
    for chunk in DOCUMENT_SEPARATOR.split(content):
        if not chunk.strip() or '{{' in chunk:
            continue
        try:
            document = yaml.safe_load(chunk)
        except yaml.YAMLError:
            continue
        if isinstance(document, dict) and document.get('kind') in WORKLOAD_KINDS:
            workloads.append(document)
    return workloads

def find_workload(workloads: list[dict], kind: str, name: str) -> dict:
    for document in workloads:
        if document.get('kind') != kind:
            continue
        if get_nested_dict(document, 'metadata').get('name') == name:
            return document
    return None

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

def reclassify(file_path: str, relative_path: str, smell: dict, workloads: list[dict]) -> None:
    global reclassified_detections
    global false_positives
    global false_positive_details
    global unresolved_workloads
    document = find_workload(workloads, smell['workload_kind'], smell['workload_label_name'])
    if document is None:
        unresolved_workloads.append({'file': relative_path,
                                     'kind': smell['workload_kind'],
                                     'workload': smell['workload_label_name']})
        return
    containers = get_pod_spec(document).get('containers')
    if not isinstance(containers, list):
        unresolved_workloads.append({'file': relative_path,
                                     'kind': smell['workload_kind'],
                                     'workload': smell['workload_label_name']})
        return
    for container in containers:
        drop = get_drop_list(container)
        if drop is None or not is_positional_smell(drop):
            continue
        reclassified_detections += 1
        if declares_all(drop):
            false_positives += 1
            false_positive_details.append({
                'file': relative_path,
                'kind': smell['workload_kind'],
                'workload': smell['workload_label_name'],
                'container': container.get('name'),
                'drop': drop,
            })

def treat_result(file_path: str, relative_path: str, result: dict) -> None:
    global flagged_workloads
    global rule_detections
    global detections_by_kind
    flagged = {}
    for kind, smells in dict(result['data']).items():
        for smell in list(smells or []):
            if smell['rule'] != RULE:
                continue
            rule_detections += 1
            if kind not in detections_by_kind:
                detections_by_kind[kind] = 0
            detections_by_kind[kind] += 1
            flagged[(smell['workload_kind'], smell['workload_label_name'])] = smell
    if not flagged:
        return
    workloads = read_workloads(file_path)
    for smell in flagged.values():
        flagged_workloads += 1
        reclassify(file_path, relative_path, smell, workloads)

def process_yaml_files(directory: str) -> None:
    global total_files
    global valid_files
    for root, _, files in os.walk(directory):
        for file in files:
            if not (file.endswith('.yaml') or file.endswith('.yml')):
                continue
            total_files += 1
            file_path = os.path.join(root, file)
            response = send_file(file_path)
            if not response.ok:
                continue
            valid_files += 1
            treat_result(file_path, os.path.relpath(file_path, directory), response.json())

process_yaml_files(sys.argv[1])
print(json.dumps({
    'total_files': total_files,
    'valid_files': valid_files,
    'rule': RULE,
    'rule_detections': rule_detections,
    'flagged_workloads': flagged_workloads,
    'reclassified_detections': reclassified_detections,
    'false_positives': false_positives,
    'false_positive_rate': false_positives/rule_detections if rule_detections else 0,
    'detections_by_kind': detections_by_kind,
    'unresolved_workloads': unresolved_workloads,
    'false_positive_details': false_positive_details,
}, indent=4))
