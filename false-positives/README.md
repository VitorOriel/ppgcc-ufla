# False positive audit

This directory contains the independent reimplementation used to audit the precision of the
`SCC_VALUE` rule of Smelly Kube over both datasets.

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

This script classifies every capabilities drop list in both datasets under **both** rules and
reports the disagreement:

| Term | Meaning |
| --- | --- |
| `positional_detections` | containers flagged by the rule as implemented in Smelly Kube |
| `kubernetes_detections` | containers that are genuinely non-compliant under Kubernetes semantics |
| `false_positives` | flagged by the positional rule, compliant under Kubernetes semantics |

The audit is exhaustive rather than sampled: it reclassifies the entire population of both
datasets, not a subset.

## How to run

The script reads YAML directly and does not require the Smelly Kube API to be running. It takes
the dataset root as its only argument and writes a JSON report to standard output.

```bash
unzip ../artifacthub.io/dataset.zip -d ../artifacthub.io/
python3 false_positives.py ../artifacthub.io/dataset > artifacthub.json
```

```bash
unzip ../github/results_consolidado_1723666729475.zip -d ../github/
python3 false_positives.py ../github/results_consolidado_1723666729475 > github.json
```

Requirements: Python 3.9 or later and `pyyaml`.

```bash
pip install pyyaml
```

## Output

The report below is the actual output of the Artifact Hub run.

```json
{
    "total_files": 5055,
    "parsed_documents": 19202,
    "skipped_documents": 3394,
    "total_workloads": 4547,
    "total_containers": 4866,
    "positional_detections": 83,
    "kubernetes_detections": 83,
    "false_positives": 0,
    "false_positive_rate": 0.0,
    "detections_by_kind": {
        "DaemonSet": 31,
        "StatefulSet": 24,
        "Job": 1,
        "Deployment": 25,
        "CronJob": 2
    },
    "false_positive_details": []
}
```

`positional_detections` and `kubernetes_detections` are equal here, which is the result the paper
reports for this dataset: all 83 detections are genuine, and none of them declares `ALL` outside
the first position of the drop list.

`false_positive_details` lists one entry per false positive, with the file, the workload kind, the
workload name, the container name and the offending `drop` list, so that every case can be
inspected manually.

## Expected figures

These are the figures reported in the paper. The Artifact Hub run above reproduces them exactly.

| Dataset | `positional_detections` | `false_positives` | Rate |
| --- | --- | --- | --- |
| Artifact Hub | 83 | 0 | 0% |
| GitHub | 901 | 5 | 0.55% |

The five GitHub false positives are concentrated in four files of two repositories, and all four
are test fixtures that other policy engines ship as examples of *compliant* configuration, namely
`pod-good.yaml` from Kyverno and `valid_example.yaml` from Regula. Manifests deliberately authored
to be correct are precisely the ones the positional test misclassifies.

## Method notes

The traversal is independent of the analyzer rather than derived from it, which is what makes the
comparison meaningful, but three conventions were kept deliberately aligned with Smelly Kube so
that the detection counts are comparable:

- Documents are separated by a line containing only `---`.
- Chunks containing `{{` are treated as Helm templates and skipped, as are chunks that fail to
  parse as YAML. Both are counted in `skipped_documents`.
- Only the seven workload kinds supported by Smelly Kube are considered: `Pod`, `Job`, `CronJob`,
  `ReplicaSet`, `Deployment`, `StatefulSet` and `DaemonSet`. The pod specification is read from
  `spec` for `Pod`, from `spec.jobTemplate.spec.template.spec` for `CronJob`, and from
  `spec.template.spec` for the remaining kinds.
- `SCC_VALUE` is evaluated only when `securityContext.capabilities` is declared on the container.
  A container that omits the field is reported by `SCC_UNSET` instead and does not enter this
  audit, which mirrors the partition between the `_UNSET` and `_VALUE` groups of the catalog.
- Capabilities are container-scoped in the Kubernetes API and admit no pod-level counterpart, so
  no pod-level fallback is applied. Only `spec.containers` is traversed, matching the analyzer.
