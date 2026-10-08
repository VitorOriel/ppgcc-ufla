import yaml
import os
import re
import json
import sys

WORKLOAD_KINDS = ['Pod', 'Job', 'CronJob', 'ReplicaSet', 'Deployment', 'StatefulSet', 'DaemonSet']
DOCUMENT_SEPARATOR = re.compile(r'^---\s*$', re.MULTILINE)

total_files = 0
parsed_documents = 0
skipped_documents = 0
total_workloads = 0
total_containers = 0
positional_detections = 0
kubernetes_detections = 0
false_positives = 0
detections_by_kind = {}
false_positive_details = []

def read_documents(file_path: str) -> list[dict]:
    global parsed_documents
    global skipped_documents
    documents = []
    with open(file_path, 'r', encoding='utf-8', errors='replace') as file:
        content = file.read()
    for chunk in DOCUMENT_SEPARATOR.split(content):
        if not chunk.strip():
            continue
        if '{{' in chunk:
            skipped_documents += 1
            continue
        try:
            document = yaml.safe_load(chunk)
        except yaml.YAMLError:
            skipped_documents += 1
            continue
        parsed_documents += 1
        if isinstance(document, dict) and document.get('kind') in WORKLOAD_KINDS:
            documents.append(document)
    return documents

def get_pod_spec(document: dict) -> dict:
    spec = document.get('spec') or {}
    if document.get('kind') == 'Pod':
        return spec
    if document.get('kind') == 'CronJob':
        job_spec = (spec.get('jobTemplate') or {}).get('spec') or {}
        return (job_spec.get('template') or {}).get('spec') or {}
    return (spec.get('template') or {}).get('spec') or {}

def get_drop_list(container: dict) -> list:
    security_context = container.get('securityContext')
    if not isinstance(security_context, dict):
        return None
    capabilities = security_context.get('capabilities')
    if not isinstance(capabilities, dict):
        return None
    drop = capabilities.get('drop')
    if drop is None:
        return []
    if not isinstance(drop, list):
        return []
    return drop

def is_positional_smell(drop: list) -> bool:
    if len(drop) == 0:
        return True
    return str(drop[0]).upper() != 'ALL'

def is_kubernetes_smell(drop: list) -> bool:
    for capability in drop:
        if str(capability).upper() == 'ALL':
            return False
    return True

def evaluate_document(file_path: str, document: dict) -> None:
    global total_workloads
    global total_containers
    global positional_detections
    global kubernetes_detections
    global false_positives
    global detections_by_kind
    global false_positive_details
    kind = document.get('kind')
    total_workloads += 1
    pod_spec = get_pod_spec(document)
    containers = pod_spec.get('containers')
    if not isinstance(containers, list):
        return
    for container in containers:
        if not isinstance(container, dict):
            continue
        total_containers += 1
        drop = get_drop_list(container)
        if drop is None:
            continue
        positional = is_positional_smell(drop)
        kubernetes = is_kubernetes_smell(drop)
        if positional:
            positional_detections += 1
            if kind not in detections_by_kind:
                detections_by_kind[kind] = 0
            detections_by_kind[kind] += 1
        if kubernetes:
            kubernetes_detections += 1
        if positional and not kubernetes:
            false_positives += 1
            false_positive_details.append({
                'file': os.path.relpath(file_path, sys.argv[1]),
                'kind': kind,
                'workload': (document.get('metadata') or {}).get('name'),
                'container': container.get('name'),
                'drop': drop,
            })

def process_yaml_files(directory: str) -> None:
    global total_files
    for root, _, files in os.walk(directory):
        for file in files:
            if not (file.endswith('.yaml') or file.endswith('.yml')):
                continue
            total_files += 1
            file_path = os.path.join(root, file)
            for document in read_documents(file_path):
                evaluate_document(file_path, document)

process_yaml_files(sys.argv[1])
print(json.dumps({
    'total_files': total_files,
    'parsed_documents': parsed_documents,
    'skipped_documents': skipped_documents,
    'total_workloads': total_workloads,
    'total_containers': total_containers,
    'positional_detections': positional_detections,
    'kubernetes_detections': kubernetes_detections,
    'false_positives': false_positives,
    'false_positive_rate': false_positives/positional_detections if positional_detections else 0,
    'detections_by_kind': detections_by_kind,
    'false_positive_details': false_positive_details,
}, indent=4))
