# False positive audit

This directory contains the audit used to measure the precision of the `SCC_VALUE` rule of
Smelly Kube over a dataset of Kubernetes manifests.

## What it evaluates

Twelve of the thirteen rules in the Smelly Kube catalog are structural predicates over fields of
the official `k8s.io/api` types: a field is either absent or set to an unsafe value, and there is
no heuristic ambiguity that could produce a false positive.

`SCC_VALUE` is the exception. It reports a container as smelly when the first element of
`securityContext.capabilities.drop` is not the literal `ALL`, compared case-insensitively:

```
len(drop) == 0  or  drop[0] != "ALL"
```

Kubernetes, however, drops every capability whenever `ALL` appears *anywhere* in that list. A
manifest written as `drop: [NET_RAW, ALL]` is therefore reported as smelly even though the
resulting configuration is equivalent to dropping all capabilities. `SCC_VALUE` is consequently the
only rule in the catalog whose predicate is stricter than the property it operationalizes, and the
only possible source of false positives.

The audit is exhaustive rather than sampled: it reclassifies every `SCC_VALUE` detection in the
dataset, not a subset.

## How it works

The audit is anchored on the detections reported by Smelly Kube rather than on an independent
detection of its own, which is what makes the result a statement about the tool. A container only
counts as a false positive if Smelly Kube flagged it.

For each manifest, the script sends the file to the Smelly Kube API, keeps the `SCC_VALUE`
detections from the response, locates the corresponding workload in the manifest by kind and name,
and reclassifies the `drop` list of each flagged container under Kubernetes semantics. A detection
is a false positive when the positional predicate reports it and `ALL` is present anywhere in the
list.

## How to run

The API has to be running first, exactly as for the analysis drivers:

```bash
git clone https://github.com/VitorOriel/security-smells-api.git
cd security-smells-api
docker compose up
```

The script then takes the dataset root as its only argument and writes a JSON report to standard
output:

```bash
python3 false_positives.py ../artifacthub.io/dataset                > artifacthub.json
python3 false_positives.py ../github/results_consolidado_1723666729475 > github.json
```

Requirements: Python 3.9 or later, `requests` and `pyyaml`.

```bash
pip install requests pyyaml
```

## Output

| Field | Meaning |
| --- | --- |
| `total_files` | files submitted to the API |
| `valid_files` | files the API accepted |
| `rule_detections` | `SCC_VALUE` detections reported by Smelly Kube |
| `flagged_workloads` | distinct workloads carrying at least one of those detections |
| `reclassified_detections` | detections the audit was able to re-examine |
| `false_positives` | detections that are compliant under Kubernetes semantics |
| `false_positive_rate` | `false_positives / rule_detections` |
| `detections_by_kind` | detections grouped by workload kind |
| `unresolved_workloads` | workloads the audit could not locate in the manifest |
| `false_positive_details` | one entry per false positive, with file, workload kind, workload name, container name and the offending `drop` list |

Two of these fields exist to audit the instrument itself rather than the tool.
`reclassified_detections` must equal `rule_detections`, and `unresolved_workloads` must be empty.
If either does not hold, the audit failed to re-examine part of the population and its
false positive count is not a lower bound on anything.

## Method notes

- Documents are separated by a line containing only `---`. Chunks containing `{{` are treated as
  Helm templates and skipped, as are chunks that fail to parse as YAML.
- Only the seven workload kinds supported by Smelly Kube are considered: `Pod`, `Job`, `CronJob`,
  `ReplicaSet`, `Deployment`, `StatefulSet` and `DaemonSet`. The pod specification is read from
  `spec` for `Pod`, from `spec.jobTemplate.spec.template.spec` for `CronJob`, and from
  `spec.template.spec` for the remaining kinds.
- A container whose `securityContext.capabilities` is absent is reported by `SCC_UNSET` instead of
  `SCC_VALUE` and never reaches this audit, which mirrors the partition between the `_UNSET` and
  `_VALUE` groups of the catalog. A container that declares `capabilities` without a `drop` list is
  reported by `SCC_VALUE` and does reach it.
- Capabilities are container-scoped in the Kubernetes API and admit no pod-level counterpart, so no
  pod-level fallback is applied. Only `spec.containers` is traversed, matching the analyser.
