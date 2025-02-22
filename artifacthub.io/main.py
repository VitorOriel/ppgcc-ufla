import requests
import os
from typing import Any
import json
import time
import sys

total_manifests = 0
valid_manifests = 0
number_of_lines = 0
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

def treat_smells(key: str, kube_smells: list[dict]) -> None:
    global smells_meta
    global workload_with_rules
    workload_meta['affected']['total'] += 1
    if key not in workload_meta['affected']:
        workload_meta['affected'][key] = 0
    workload_meta['affected'][key] += 1
    if key not in workload_with_rules:
        workload_with_rules[key] = {}
    for smell in kube_smells:
        rule = smell['rule']
        if rule not in smells_meta:
            smells_meta[rule] = 0
        smells_meta[rule] += 1
        if rule not in workload_with_rules[key]:
            workload_with_rules[key][rule] = 0
        workload_with_rules[key][rule] += 1

def treat_result(result: dict[str, dict]) -> None:
    global workload_meta
    global smells_meta
    smells_meta['total'] += result['meta']['totalOfSmells']
    for key, value in dict(result['meta']['decodedWorkloads']).items():
        workload_meta['decoded']['total'] += int(value)
        if key not in workload_meta['decoded']:
            workload_meta['decoded'][key] = 0
        workload_meta['decoded'][key] += int(value)
    for key, value in dict(result['data']).items():
        if key not in workload_meta['smells']:
            workload_meta['smells'][key] = 0
        kube_smells: list[dict[str, Any]] = list(value)
        workload_meta['smells'][key] += len(kube_smells)
        if kube_smells:
            treat_smells(key, kube_smells)

def evaluate_number_of_lines(file_path: str) -> None:
    global number_of_lines
    with open(file_path, 'r') as file:
        for line in file.readlines():
            line = line.strip()
            if line and not line.startswith('#'):
                number_of_lines += 1

def process_yaml_files(directory: str):
    global total_manifests
    global valid_manifests
    global all_manifests
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith('.yaml'):
                total_manifests += 1
                file_path = os.path.join(root, file)
                response = send_file(file_path)
                if response.ok:
                    valid_manifests += 1
                    treat_result(response.json())
                    evaluate_number_of_lines(file_path)
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
    return f"{top_rule} with {greater} smells"

before = time.time()
process_yaml_files(sys.argv[1])
total_time = int(time.time()-before)
print(json.dumps({
    'total_manifests': total_manifests,
    'valid_manifests': valid_manifests,
    'number_of_lines': number_of_lines,
    'workload_meta': workload_meta,
    'smells_meta': smells_meta,
    'workload_with_rules': {
        'top_rule': {
            workload: get_top_rule(rule_dict)
            for workload, rule_dict in workload_with_rules.items()
        },
        'details': workload_with_rules,
    },
    'smells_density': {
        'by_lines': {
            key: value/(number_of_lines/1000)
            for key, value in smells_meta.items()
            if key != "total"
        },
        'by_workloads': {
            key: value/workload_meta['decoded']['total']
            for key, value in smells_meta.items()
            if key != "total"
        }
    },
    'top_10_lowest': [f"{manifest['file']}: {manifest['json']['meta']['totalOfSmells']}" for manifest in all_manifests[:10]],
    'top_10_highest': [f"{manifest['file']}: {manifest['json']['meta']['totalOfSmells']}" for manifest in all_manifests[len(all_manifests)-10:]],
    'time_taken': f"{int(total_time/60)} minutes and {total_time%60} seconds",
}, indent=4))