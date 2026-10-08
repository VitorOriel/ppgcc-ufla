# False Negatives

In this directory can be found the script to measure what the analyzers never reach: initialization and ephemeral containers, containers that add capabilities back after dropping them, and documents whose kind falls outside the supported workload kinds but that still embed a container list.

## Tests and Results

The Python script `false_negatives.py` is responsible to run the tests. You must:
1. Unzip the datasets of the `artifacthub.io` and `github` directories;
2. Run the tests (`python3 false_negatives.py ../artifacthub.io/dataset/` and `python3 false_negatives.py ../github/results_consolidado_1723666729475/`);

The script reads the datasets from disk and does not require the smelly-kube-api.
