# PPGCC-UFLA

This repository provides the abstract, the applications and a sample, related to the dissertation "Smelly Kube: A tool used to identify security smells in Kubernetes infrastructure manifests" submitted to the *Programa de Pós-Graduação em Ciência da Computação na Universidade Federal de Lavras*.

## Software
Both Smelly Kube API and Visual Studio Code plugin can be found in the following repositories, which contains information about the applications technologies and dependencies, and instructions to run them.

- [security-smells-api](https://github.com/VitorOriel/security-smells-api/tree): The Smelly Kube API (server) repository
- [smelly-kube-vscode-plugin](https://github.com/VitorOriel/smelly-kube-vscode-plugin/tree/): The Smelly Kube Visual Studio Code (client) repository

In [samples](./samples/) can be found a sample Kubernetes manifest to try out the Smelly Kube API. Also, a curl request and the expected JSON response.

## Dataset, Tests and Results

The directory [artifacthub.io](./artifacthub.io/) presents instructions to generate the dataset from artifacthub.io, and the script used to run the tests.

## Paper abstract
The Kubernetes platform has stood out for the orchestration and management of microservices due to its ability to handle large volumes of services and its scalability. However, neglecting security when designing Kubernetes manifests can lead to significant risks, leaving microservices susceptible to various vulnerabilities. This work presents Smelly Kube, a tool for identifying security smells in Kubernetes manifests. It was developed using a client/server architecture, comprising: i) Client: a Visual Studio Code plugin, and ii) Server: an application developed in Golang to analyze these manifests and identify the security smells. Integration with Visual Studio Code offers developers a user-friendly and efficient interface to perform security checks directly in the development environment, facilitating the adoption and continuous use of the tool. A case study was conducted to validate the tool’s effectiveness, using real-world production scenarios and various microservices configurations. The results showed that Smelly Kube is promising and may contribute to the security maturity of overall Kubernetes applications.