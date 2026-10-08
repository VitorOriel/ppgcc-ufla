# Deduplication

In this directory can be found the script to measure how much of each dataset is duplicated content, at the file level and at the decoded workload level, and how much the two datasets share.

## Tests and Results

The Python script `dedup.py` is responsible to run the tests. You must:
1. Unzip the datasets of the `artifacthub.io` and `github` directories;
2. Run the smelly-kube-api;
3. Run the tests (`python3 dedup.py ../artifacthub.io/dataset/` and `python3 dedup.py ../github/results_consolidado_1723666729475/`);

The script takes one or more dataset roots. Passing both in the same run (`python3 dedup.py ../artifacthub.io/dataset/ ../github/results_consolidado_1723666729475/`) also reports how many files and workload configurations occur in both.
