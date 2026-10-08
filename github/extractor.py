import requests
import os
import re
import csv
import json
import time
import sys

API = 'https://api.github.com'
RAW = 'https://raw.githubusercontent.com'
TOKEN = os.environ.get('GITHUB_TOKEN')
REPOSITORY_QUERY = os.environ.get('REPOSITORY_QUERY', 'topic:kubernetes')
STARS_WINDOWS = [
    '0..9', '10..24', '25..49', '50..99', '100..199', '200..399',
    '400..799', '800..1599', '1600..3199', '3200..6399', '>=6400',
]
APIVERSION_PATTERN = re.compile(r'apiVersion:\s*(\S+)\s*\n')
KIND_PATTERN = re.compile(r'kind:\s*(\S+)\s*\n')
YAML_EXTENSIONS = ('.yaml', '.yml')
CSV_COLUMNS = [
    'id', 'full_name', 'description', 'created_at', 'updated_at', 'pushed_at',
    'html_url', 'stargazers_count', 'language', 'forks_count',
    'open_issues_count', 'topics', 'network_count', 'subscribers_count',
]

session = requests.Session()
repositories = {}
collected_files = []
total_candidates = 0
total_downloaded = 0
total_rejected = 0
total_skipped = 0
failed_requests = []

def headers() -> dict:
    value = {'Accept': 'application/vnd.github+json'}
    if TOKEN:
        value['Authorization'] = f"Bearer {TOKEN}"
    return value

def wait_for_rate_limit(response: requests.Response) -> bool:
    if response.status_code not in (403, 429):
        return False
    remaining = response.headers.get('X-RateLimit-Remaining')
    reset = response.headers.get('X-RateLimit-Reset')
    if remaining is not None and remaining != '0':
        return False
    if reset is None:
        time.sleep(60)
        return True
    delay = int(reset) - int(time.time()) + 5
    if delay > 0:
        print(f"rate limit reached, sleeping {delay}s", file=sys.stderr)
        time.sleep(delay)
    return True

def github_get(url: str, params: dict = None) -> dict:
    global failed_requests
    for _ in range(5):
        response = session.get(url, headers=headers(), params=params, timeout=60)
        if wait_for_rate_limit(response):
            continue
        if response.status_code == 200:
            return response.json()
        if response.status_code in (404, 409, 451):
            return None
        time.sleep(5)
    failed_requests.append({'url': url, 'params': params, 'status': response.status_code})
    return None

def search_repositories(stars_window: str) -> None:
    global repositories
    query = f"{REPOSITORY_QUERY} stars:{stars_window}"
    for page in range(1, 11):
        payload = github_get(f"{API}/search/repositories", {
            'q': query,
            'sort': 'stars',
            'order': 'desc',
            'per_page': 100,
            'page': page,
        })
        if not payload or not payload.get('items'):
            return
        for item in payload['items']:
            repositories[item['id']] = {'full_name': item['full_name'],
                                        'default_branch': item['default_branch']}
        if len(payload['items']) < 100:
            return

def describe_repository(full_name: str) -> dict:
    payload = github_get(f"{API}/repos/{full_name}")
    if not payload:
        return None
    return {column: payload.get(column) for column in CSV_COLUMNS}

def list_yaml_paths(full_name: str, default_branch: str) -> list[str]:
    payload = github_get(f"{API}/repos/{full_name}/git/trees/{default_branch}",
                         {'recursive': '1'})
    if not payload:
        return []
    paths = []
    for entry in payload.get('tree') or []:
        if entry.get('type') != 'blob':
            continue
        path = entry.get('path') or ''
        if path.endswith(YAML_EXTENSIONS):
            paths.append(path)
    return paths

def is_kubernetes_manifest(content: str) -> bool:
    return bool(APIVERSION_PATTERN.search(content)) and bool(KIND_PATTERN.search(content))

def download_file(full_name: str, default_branch: str, path: str, output: str) -> None:
    global total_downloaded
    global total_rejected
    global total_skipped
    global collected_files
    destination = os.path.join(output, full_name, path)
    if os.path.exists(destination):
        total_skipped += 1
        collected_files.append((full_name, path))
        return
    response = session.get(f"{RAW}/{full_name}/{default_branch}/{path}", timeout=60)
    if response.status_code != 200:
        failed_requests.append({'url': response.url, 'status': response.status_code})
        return
    content = response.content.decode('utf-8', errors='replace')
    if not is_kubernetes_manifest(content):
        total_rejected += 1
        return
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    with open(destination, 'w', encoding='utf-8') as file:
        file.write(content)
    total_downloaded += 1
    collected_files.append((full_name, path))

def write_files_csv(output: str, descriptions: dict) -> None:
    with open(os.path.join(output, 'files.csv'), 'w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file, quoting=csv.QUOTE_NONNUMERIC)
        writer.writerow(['repo_id', 'repo_name', 'file'])
        for full_name, path in collected_files:
            description = descriptions.get(full_name)
            if not description:
                continue
            writer.writerow([description['id'], full_name, f"{full_name}/{path}"])

def write_repositories_csv(output: str, descriptions: dict) -> None:
    with open(os.path.join(output, 'repositories.csv'), 'w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file, quoting=csv.QUOTE_NONNUMERIC)
        writer.writerow(CSV_COLUMNS)
        for description in descriptions.values():
            row = []
            for column in CSV_COLUMNS:
                value = description.get(column)
                if column == 'topics':
                    row.append(json.dumps(value or []))
                elif value is None:
                    row.append('')
                else:
                    row.append(value)
            writer.writerow(row)

def extract(output: str) -> None:
    global total_candidates
    os.makedirs(output, exist_ok=True)
    for stars_window in STARS_WINDOWS:
        search_repositories(stars_window)
        print(f"window {stars_window}: {len(repositories)} repositories so far", file=sys.stderr)
    descriptions = {}
    for index, repository in enumerate(repositories.values(), 1):
        full_name = repository['full_name']
        description = describe_repository(full_name)
        if not description:
            continue
        descriptions[full_name] = description
        for path in list_yaml_paths(full_name, repository['default_branch']):
            total_candidates += 1
            download_file(full_name, repository['default_branch'], path, output)
        if index % 50 == 0:
            print(f"{index}/{len(repositories)} repositories processed", file=sys.stderr)
    write_files_csv(output, descriptions)
    write_repositories_csv(output, descriptions)

if not TOKEN:
    print("GITHUB_TOKEN is not set; the search and tree endpoints will be rate limited to 60 requests per hour", file=sys.stderr)
before = time.time()
extract(sys.argv[1])
total_time = int(time.time()-before)
print(json.dumps({
    'repository_query': REPOSITORY_QUERY,
    'stars_windows': STARS_WINDOWS,
    'total_repositories': len(repositories),
    'total_candidates': total_candidates,
    'total_downloaded': total_downloaded,
    'total_skipped': total_skipped,
    'total_rejected': total_rejected,
    'total_collected': len(collected_files),
    'failed_requests': len(failed_requests),
    'time_taken': f"{int(total_time/60)} minutes and {total_time%60} seconds",
}, indent=4))
