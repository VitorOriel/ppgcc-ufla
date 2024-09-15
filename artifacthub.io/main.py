import requests
import os
from typing import Any
import json
import time
import sys

total_manifests = 0
valid_manifests = 0
workload_meta = {'decoded': {'total': 0}, 'affected': {'total': 0}, 'smells': {}}
smells_meta = {'total': 0}
workload_with_rules = {}
all_manifests = []

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
    global all_manifests
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith('.yaml'):
                total_manifests += 1
                response = send_file(os.path.join(root, file))
                if response.ok:
                    valid_manifests += 1
                    threat_result(response.json())
                    all_manifests.append({'file': file, 'json': response.json()})
    all_manifests = sorted(all_manifests, key=lambda x: x['json']['meta']['totalOfSmells'])

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
process_yaml_files(sys.argv[1])
total_time = int(time.time()-before)
print(json.dumps({
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
    'top_10_lowest': [f"{manifest['file']}: {manifest['json']['meta']['totalOfSmells']}" for manifest in all_manifests[:10]],
    'top_10_highest': [f"{manifest['file']}: {manifest['json']['meta']['totalOfSmells']}" for manifest in all_manifests[len(all_manifests)-10:]],
    'time_taken': f"{int(total_time/60)} minutes and {total_time%60} seconds",
}, indent=4))