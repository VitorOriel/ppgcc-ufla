import requests
import os
import json
import sys
import time

API_URL = "http://localhost:3000/api/v1/smelly"
PROGRESS_EVERY = 500

# A rule family groups the unset and the misconfigured predicate over the same field.
# A control is not enforced when either fires, so the family is the unit that compares
# with a policy stated as the absence of enforcement.
FAMILIES = {
    'resourceRequests': ['K8S_SEC_RESREQUESTS_UNSET'],
    'resourceLimits': ['K8S_SEC_RESLIMITS_UNSET'],
    'runAsUser': ['K8S_SEC_RUNASUSER_UNSET', 'K8S_SEC_RUNASUSER_VALUE'],
    'runAsNonRoot': ['K8S_SEC_RUNASNONROOT_UNSET', 'K8S_SEC_RUNASNONROOT_VALUE'],
    'capabilities': ['K8S_SEC_CAPABILITIES_UNSET', 'K8S_SEC_CAPABILITIES_VALUE'],
    'allowPrivilegeEscalation': ['K8S_SEC_PRIVESCALATION_UNSET', 'K8S_SEC_PRIVESCALATION_VALUE'],
    'readOnlyRootFilesystem': ['K8S_SEC_ROROOTFS_UNSET', 'K8S_SEC_ROROOTFS_VALUE'],
    'privileged': ['K8S_SEC_PRIVILEGED_VALUE'],
}
RULE_TO_FAMILY = {rule: family for family, rules in FAMILIES.items() for rule in rules}

total_files = 0
valid_files = 0
manifests_with_rule = {}
manifests_with_family = {}
occurrences_by_rule = {}
unmapped_rules = set()

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

def rules_in_result(result: dict) -> dict:
    counted = {}
    for _, smells in dict(result['data']).items():
        for smell in list(smells or []):
            rule = smell['rule']
            counted[rule] = counted.get(rule, 0) + 1
    return counted

def process_yaml_files(directory: str) -> None:
    global total_files
    global valid_files
    paths = collect_files(directory)
    population = len(paths)
    print(f"{population} files to process", file=sys.stderr, flush=True)
    for index, file_path in enumerate(paths, start=1):
        total_files += 1
        if index % PROGRESS_EVERY == 0 or index == population:
            print(f"progress {index}/{population} valid={valid_files}", file=sys.stderr, flush=True)
        response = send_file(file_path)
        if not response.ok:
            continue
        valid_files += 1
        counted = rules_in_result(response.json())
        families = set()
        for rule, occurrences in counted.items():
            manifests_with_rule[rule] = manifests_with_rule.get(rule, 0) + 1
            occurrences_by_rule[rule] = occurrences_by_rule.get(rule, 0) + occurrences
            family = RULE_TO_FAMILY.get(rule)
            if family is None:
                unmapped_rules.add(rule)
            else:
                families.add(family)
        for family in families:
            manifests_with_family[family] = manifests_with_family.get(family, 0) + 1

process_yaml_files(sys.argv[1])
total_occurrences = sum(occurrences_by_rule.values())
print(json.dumps({
    'total_files': total_files,
    'valid_files': valid_files,
    'unit': 'valid manifest; on Artifact Hub one manifest is one rendered chart',
    'prevalence_by_rule': {
        rule: {
            'manifests': manifests_with_rule[rule],
            'percent_of_valid_manifests': round(100 * manifests_with_rule[rule] / valid_files, 2) if valid_files else 0,
        }
        for rule in sorted(manifests_with_rule, key=lambda r: -manifests_with_rule[r])
    },
    'prevalence_by_family': {
        family: {
            'rules': FAMILIES[family],
            'manifests': manifests_with_family[family],
            'percent_of_valid_manifests': round(100 * manifests_with_family[family] / valid_files, 2) if valid_files else 0,
        }
        for family in sorted(manifests_with_family, key=lambda f: -manifests_with_family[f])
    },
    'unmapped_rules': sorted(unmapped_rules),
    'occurrences_by_rule': {
        rule: {
            'occurrences': occurrences_by_rule[rule],
            'percent_of_all_smells': round(100 * occurrences_by_rule[rule] / total_occurrences, 2) if total_occurrences else 0,
        }
        for rule in sorted(occurrences_by_rule, key=lambda r: -occurrences_by_rule[r])
    },
    'total_occurrences': total_occurrences,
}, indent=4))
