import requests
import csv
import json
import os
import sys
import time

API = 'https://api.github.com'
TOKEN = os.environ.get('GITHUB_TOKEN')
PROGRESS_EVERY = 200

session = requests.Session()

counts = {'rows': 0, 'queried': 0, 'forks': 0, 'sources': 0, 'not_found': 0, 'failed': 0}
forked_repositories = []

def headers() -> dict:
    base = {'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'}
    if TOKEN:
        base['Authorization'] = f"Bearer {TOKEN}"
    return base

def wait_for_rate_limit(response: requests.Response) -> bool:
    if response.status_code not in (403, 429):
        return False
    remaining = response.headers.get('X-RateLimit-Remaining')
    reset = response.headers.get('X-RateLimit-Reset')
    if remaining == '0' and reset:
        delay = max(1, int(reset) - int(time.time()) + 2)
        print(f"rate limited, sleeping {delay}s", file=sys.stderr, flush=True)
        time.sleep(delay)
        return True
    retry_after = response.headers.get('Retry-After')
    if retry_after:
        time.sleep(int(retry_after) + 1)
        return True
    return False

def describe(full_name: str) -> dict:
    url = f"{API}/repos/{full_name}"
    for attempt in range(5):
        try:
            response = session.get(url, headers=headers(), timeout=60)
        except requests.exceptions.RequestException as error:
            print(f"retry {attempt+1}/5 on {full_name}: {error}", file=sys.stderr, flush=True)
            time.sleep(2 ** attempt)
            continue
        if wait_for_rate_limit(response):
            continue
        if response.status_code == 404:
            return {'status': 'not_found'}
        if not response.ok:
            print(f"http {response.status_code} on {full_name}", file=sys.stderr, flush=True)
            time.sleep(2 ** attempt)
            continue
        payload = response.json()
        return {'status': 'ok', 'fork': bool(payload.get('fork')),
                'full_name': payload.get('full_name'),
                'parent': (payload.get('parent') or {}).get('full_name')}
    return {'status': 'failed'}

def read_repository_names(path: str) -> list[str]:
    names = []
    with open(path, newline='', encoding='utf-8', errors='replace') as handle:
        for row in csv.DictReader(handle):
            name = (row.get('full_name') or '').strip()
            if name:
                names.append(name)
    return names

names = read_repository_names(sys.argv[1])
counts['rows'] = len(names)
print(f"{len(names)} repositories to query", file=sys.stderr, flush=True)
for index, full_name in enumerate(names, start=1):
    if index % PROGRESS_EVERY == 0 or index == len(names):
        print(f"progress {index}/{len(names)} forks={counts['forks']} "
              f"not_found={counts['not_found']}", file=sys.stderr, flush=True)
    outcome = describe(full_name)
    if outcome['status'] == 'not_found':
        counts['not_found'] += 1
        continue
    if outcome['status'] == 'failed':
        counts['failed'] += 1
        continue
    counts['queried'] += 1
    if outcome['fork']:
        counts['forks'] += 1
        forked_repositories.append({'queried_as': full_name,
                                    'current_name': outcome['full_name'],
                                    'parent': outcome['parent']})
    else:
        counts['sources'] += 1

print(json.dumps({
    'counts': counts,
    'fork_rate_over_queried': round(counts['forks'] / counts['queried'], 4) if counts['queried'] else 0,
    'forked_repositories': forked_repositories,
}, indent=4))
