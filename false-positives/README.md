# False Positives

In this directory can be found the script to audit the false positives of the `K8S_SEC_CAPABILITIES_VALUE` rule over both datasets.

## Tests and Results

The Python script `false_positives.py` is responsible to run the tests. You must:
1. Unzip the datasets of the `artifacthub.io` and `github` directories;
2. Run the smelly-kube-api;
3. Run the tests (`python3 false_positives.py ../artifacthub.io/dataset/` and `python3 false_positives.py ../github/results_consolidado_1723666729475/`);
