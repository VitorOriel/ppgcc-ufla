import requests
import os
from typing import Any
import json
import time

total_manifests = 0
valid_manifests = 0
total_projects = 0
valid_projects = 0
workload_meta = {'decoded': {'total': 0}, 'affected': {'total': 0}, 'smells': {}}
smells_meta = {'total': 0}
workload_with_rules = {}
all_manifests = []
project_dict = {}

def send_file(file_path: str) -> requests.Response:
    body = {}
    with open(file_path, 'r') as file:
        body = {
            'FileName': file_path,
            'YamlToValidate': file.read(),
        }
    response = requests.post(
        "http://localhost:3000/api/v1/smelly",
        headers={
            'Content-Type': "application/json",
        },
        json=body
    )
    return response

def threat_result(result: dict[str, dict]) -> None:
    global workload_meta
    global smells_meta
    global workload_with_rules
    smells_meta['total'] += result['meta']['totalOfSmells']
    for key, value in dict(result['meta']['decodedWorkloads']).items():
        workload_meta['decoded']['total'] += int(value)
        if key not in workload_meta['decoded']:
            workload_meta['decoded'][key] = 0
        workload_meta['decoded'][key] += int(value)
    for key, value in dict(result['data']).items():
        if key not in workload_meta['smells']:
            workload_meta['smells'][key] = 0
        kubeSmells: list[dict[str, Any]] = list(value)
        workload_meta['smells'][key] += len(kubeSmells)
        if kubeSmells:
            workload_meta['affected']['total'] += 1
            if key not in workload_meta['affected']:
                workload_meta['affected'][key] = 0
            workload_meta['affected'][key] += 1
            if key not in workload_with_rules:
                workload_with_rules[key] = {}
            for smell in kubeSmells:
                rule = smell['rule']
                if rule not in smells_meta:
                    smells_meta[rule] = 0
                smells_meta[rule] += 1
                if rule not in workload_with_rules[key]:
                    workload_with_rules[key][rule] = 0
                workload_with_rules[key][rule] += 1

def process_yaml_files(directory: str):
    global total_manifests
    global valid_manifests
    global total_projects
    global valid_projects
    global all_manifests
    global project_dict
    directories = [entry for entry in os.listdir(directory) if os.path.isdir(os.path.join(directory, entry))]
    for dir_name in directories:
        total_projects += 1
        project_dict[dir_name] = []
        for root_dir, _, files in os.walk(os.path.join(directory, dir_name)):
            for file in files:
                if file.endswith('.yaml') or file.endswith('.yml'):
                    total_manifests += 1
                    response = send_file(os.path.join(root_dir, file))
                    if response.ok:
                        valid_manifests += 1
                        threat_result(response.json())
                        project_dict[dir_name].append(response.json())
        if project_dict[dir_name]:
            valid_projects += 1
            compiled_manifest = {'project': dir_name, 'totalOfSmells': 0}
            for project in project_dict[dir_name]:
                compiled_manifest['totalOfSmells'] += project['meta']['totalOfSmells']
            all_manifests.append(compiled_manifest)
    all_manifests = sorted(all_manifests, key=lambda x: x['totalOfSmells'])

def get_top_rule(rule_dict: dict[str, int]) -> str:
    top_rule = ''
    greater = 0
    for key, value in rule_dict.items():
        if not top_rule:
            top_rule, greater = key, value
            continue
        if greater < value:
            top_rule, greater = key, value
    return top_rule

before = time.time()
process_yaml_files("./results_consolidado_1722891954636")
total_time = int(time.time()-before)
print(json.dumps({
    'total_projects': total_projects,
    'valid_projects': valid_projects,
    'total_manifests': total_manifests,
    'valid_manifests': valid_manifests,
    'workload_meta': workload_meta,
    'smells_meta': smells_meta,
    'workload_with_rules': {
        'top_rule': {
            workload: get_top_rule(rule_dict)
            for workload, rule_dict in workload_with_rules.items()
        },
        'details': workload_with_rules,
    },
    'top_10_lowest': [f"{manifest['project']}: {manifest['totalOfSmells']}" for manifest in all_manifests[:10]],
    'top_10_highest': [f"{manifest['project']}: {manifest['totalOfSmells']}" for manifest in all_manifests[len(all_manifests)-10:]],
    'time_taken': f"{int(total_time/60)} minutes and {total_time%60} seconds",
}, indent=4))