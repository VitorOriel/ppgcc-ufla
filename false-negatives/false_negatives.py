import yaml
import os
import json
import re
import sys

PROGRESS_EVERY = 20000
LINE_SEPARATOR = re.compile(r'(?m)^---\s*$')
SUBSTRING_SEPARATOR = '---'
WORKLOAD_KINDS = ['Pod', 'Job', 'CronJob', 'ReplicaSet', 'Deployment', 'StatefulSet', 'DaemonSet']
TRACKED_CAPABILITIES = ['SYS_ADMIN', 'NET_ADMIN', 'SYS_PTRACE', 'SYS_MODULE', 'ALL']

# Traversal variants, exposed so that the choices behind the reported figures can be
# inspected and varied. The defaults below are the combination the reported figures
# come from, and the only one that reproduces them.
# 'iteration' selects how a file is split into documents: 'chunk' splits first and
# discards only a malformed fragment, 'file' hands the whole file to the YAML loader so
# that one malformed document discards the file.
# 'separator' selects the document separator: 'substring' cuts wherever three hyphens
# occur, which is what the analyzer under study does, and 'line' requires a line
# containing exactly three hyphens.
# 'podspec' selects what counts as an embedded pod specification in a document whose
# kind is out of scope: 'containers' requires a container list, 'any' also accepts a
# list of initialization containers alone.
ITERATION = os.environ.get('ITERATION', 'chunk')
SEPARATOR = os.environ.get('SEPARATOR', 'substring')
PODSPEC = os.environ.get('PODSPEC', 'containers')

total_files = 0
dropped_files = 0
dropped_documents = 0

out_of_scope = {
    'documents': 0,
    'documents_with_pod_spec': 0,
    'containers': 0,
    'init_containers': 0,
    'alpha_api_versions': 0,
    'beta_api_versions': 0,
    'by_kind': {},
    'by_api_group': {},
}

in_scope = {
    'workloads': 0,
    'init_containers': 0,
    'workloads_with_init_containers': 0,
    'privileged_init_containers': 0,
    'ephemeral_containers': 0,
    'workloads_with_ephemeral_containers': 0,
    'privileged_ephemeral_containers': 0,
}

capabilities_add = {
    'containers': 0,
    'containers_with_add': 0,
    'workloads_with_add': 0,
    'by_capability': {capability: 0 for capability in TRACKED_CAPABILITIES},
    'drops_all_and_adds': 0,
}

def collect_files(directory: str) -> list[str]:
    paths = []
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith('.yaml') or file.endswith('.yml'):
                paths.append(os.path.join(root, file))
    paths.sort()
    return paths

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

def split_documents(content: str) -> list[str]:
    if SEPARATOR == 'substring':
        return content.split(SUBSTRING_SEPARATOR)
    return LINE_SEPARATOR.split(content)

def decode_documents(file_path: str) -> list[dict]:
    global dropped_files
    global dropped_documents
    with open(file_path, 'r', encoding='utf-8', errors='replace') as file:
        content = file.read()
    if ITERATION == 'file':
        try:
            loaded = list(yaml.safe_load_all(content))
        except yaml.YAMLError:
            dropped_files += 1
            return []
        return [document for document in loaded if isinstance(document, dict)]
    documents = []
    for chunk in split_documents(content):
        if len(chunk.strip()) == 0:
            continue
        try:
            document = yaml.safe_load(chunk)
        except yaml.YAMLError:
            dropped_documents += 1
            continue
        if isinstance(document, dict):
            documents.append(document)
    return documents

def container_lists_at_any_depth(value, key: str) -> list[list]:
    found = []
    if isinstance(value, dict):
        nested = value.get(key)
        if isinstance(nested, list):
            found.append(nested)
        for child in value.values():
            found.extend(container_lists_at_any_depth(child, key))
    elif isinstance(value, list):
        for child in value:
            found.extend(container_lists_at_any_depth(child, key))
    return found

def count_containers_at_any_depth(document: dict, key: str) -> int:
    counted = 0
    for container_list in container_lists_at_any_depth(document, key):
        counted += len(container_list)
    return counted

def get_api_group(document: dict) -> str:
    api_version = str(document.get('apiVersion') or '')
    if '/' not in api_version:
        return 'core'
    return api_version.split('/', 1)[0]

def is_privileged(container) -> bool:
    if not isinstance(container, dict):
        return False
    return get_nested_dict(container, 'securityContext').get('privileged') is True

def get_capability_list(container, key: str) -> list:
    if not isinstance(container, dict):
        return []
    capabilities = get_nested_dict(get_nested_dict(container, 'securityContext'), 'capabilities')
    value = capabilities.get(key)
    if not isinstance(value, list):
        return []
    return value

def examine_out_of_scope(document: dict) -> None:
    out_of_scope['documents'] += 1
    containers = count_containers_at_any_depth(document, 'containers')
    init_containers = count_containers_at_any_depth(document, 'initContainers')
    carries_pod_spec = containers > 0 if PODSPEC == 'containers' else (containers > 0 or init_containers > 0)
    if not carries_pod_spec:
        return
    out_of_scope['documents_with_pod_spec'] += 1
    out_of_scope['containers'] += containers
    out_of_scope['init_containers'] += init_containers
    api_version = str(document.get('apiVersion') or '')
    if 'alpha' in api_version:
        out_of_scope['alpha_api_versions'] += 1
    elif 'beta' in api_version:
        out_of_scope['beta_api_versions'] += 1
    kind = str(document.get('kind') or 'None')
    entry = out_of_scope['by_kind'].setdefault(kind, {'documents': 0, 'containers': 0, 'init_containers': 0})
    entry['documents'] += 1
    entry['containers'] += containers
    entry['init_containers'] += init_containers
    group = get_api_group(document)
    group_entry = out_of_scope['by_api_group'].setdefault(group, {'documents': 0, 'containers': 0})
    group_entry['documents'] += 1
    group_entry['containers'] += containers

def examine_in_scope(document: dict) -> None:
    in_scope['workloads'] += 1
    pod_spec = get_pod_spec(document)
    init_containers = pod_spec.get('initContainers')
    if isinstance(init_containers, list) and init_containers:
        in_scope['workloads_with_init_containers'] += 1
        in_scope['init_containers'] += len(init_containers)
        for container in init_containers:
            if is_privileged(container):
                in_scope['privileged_init_containers'] += 1
    ephemeral_containers = pod_spec.get('ephemeralContainers')
    if isinstance(ephemeral_containers, list) and ephemeral_containers:
        in_scope['workloads_with_ephemeral_containers'] += 1
        in_scope['ephemeral_containers'] += len(ephemeral_containers)
        for container in ephemeral_containers:
            if is_privileged(container):
                in_scope['privileged_ephemeral_containers'] += 1
    containers = pod_spec.get('containers')
    if not isinstance(containers, list):
        return
    workload_has_add = False
    for container in containers:
        capabilities_add['containers'] += 1
        add = get_capability_list(container, 'add')
        if not add:
            continue
        workload_has_add = True
        capabilities_add['containers_with_add'] += 1
        declared = {str(capability).upper() for capability in add}
        for capability in TRACKED_CAPABILITIES:
            if capability in declared:
                capabilities_add['by_capability'][capability] += 1
        drop = {str(capability).upper() for capability in get_capability_list(container, 'drop')}
        if 'ALL' in drop:
            capabilities_add['drops_all_and_adds'] += 1
    if workload_has_add:
        capabilities_add['workloads_with_add'] += 1

def process_yaml_files(directory: str) -> None:
    global total_files
    paths = collect_files(directory)
    population = len(paths)
    print(f"{population} files to process", file=sys.stderr, flush=True)
    for index, file_path in enumerate(paths, start=1):
        total_files += 1
        if index % PROGRESS_EVERY == 0 or index == population:
            print(f"progress {index}/{population}", file=sys.stderr, flush=True)
        for document in decode_documents(file_path):
            if document.get('kind') in WORKLOAD_KINDS:
                examine_in_scope(document)
            else:
                examine_out_of_scope(document)

process_yaml_files(sys.argv[1])
out_of_scope['by_kind'] = dict(sorted(out_of_scope['by_kind'].items(),
                                      key=lambda item: -item[1]['documents']))
out_of_scope['by_api_group'] = dict(sorted(out_of_scope['by_api_group'].items(),
                                          key=lambda item: -item[1]['documents']))
print(json.dumps({
    'variant': {'iteration': ITERATION, 'separator': SEPARATOR, 'podspec': PODSPEC},
    'total_files': total_files,
    'dropped_files': dropped_files,
    'dropped_documents': dropped_documents,
    'out_of_scope_kinds': out_of_scope,
    'init_and_ephemeral_containers': in_scope,
    'capabilities_add_list': capabilities_add,
}, indent=4))
