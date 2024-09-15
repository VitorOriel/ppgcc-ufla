#!/bin/bash

# Command to retrieve the JSON
json=$(curl -X 'GET' \
    'https://artifacthub.io/api/v1/helm-exporter' \
    -H 'accept: application/json' \
    -H 'X-API-KEY-ID: ${API_KEY_ID}' \
    -H 'X-API-KEY-SECRET: ${API_KEY_SECRET}')

# Loop through each entry in the JSON
for entry in $(echo "$json" | jq -c '.[]'); do
    # Extract the name, version, and repository URL from the entry
    name=$(echo "$entry" | jq -r '.name')
    version=$(echo "$entry" | jq -r '.version')
    repoUrl=$(echo "$entry" | jq -r '.repository.url')

    # Add the repository
    helm repo add "$name" "$repoUrl"

    # Install the Helm chart with --debug and --dry-run, outputting to a manifest file
    helm install "${name}-release" "$name/$name" --version "$version" --debug --dry-run > "${name}-manifest.yaml"
done
