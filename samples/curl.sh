# !/bin/sh
# This is the curl http request for smelly kube api, sending the manifest.yaml
# in the request body

curl http://localhost:3000/api/v1/smelly -d '{"fileName": "manifest.yaml", "yamlToValidate": "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: http-server\nspec:\n  replicas: 1\n  selector:\n    matchLabels:\n      app: http-server\n  template:\n    metadata:\n      labels:\n        app: http-server\n    spec:\n      serviceAccountName: http-server-sa\n      containers:\n      - name: http-server\n        image: python:3.9-slim\n        ports:\n        - containerPort: 8000\n        command: [ \"python\", \"http_server_builtin.py\" ]"}' -X POST -H 'Content-Type: application/json'