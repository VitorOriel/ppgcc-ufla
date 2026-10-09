# Prevalence

In this directory can be found the script to measure, for each rule of the catalog, the share of valid manifests in which that rule occurs at least once.

## Tests and Results

The Python script `prevalence.py` is responsible to run the tests. You must:
1. Unzip the datasets of the `artifacthub.io` and `github` directories;
2. Run the smelly-kube-api with `docker compose up -d`;
3. Run the tests (`python3 prevalence.py ../artifacthub.io/dataset/` and `python3 prevalence.py ../github/results_consolidado_1723666729475/`);
