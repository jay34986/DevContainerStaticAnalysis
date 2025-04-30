# DevContainer for Static Analysis

## Overview

This is a Visual Studio Code (VS Code) DevContainer environment based on Amazon Linux 2023.  
The DevContainer is configured with Linters and VS Code extensions.

## DevContainer Base Image

- public.ecr.aws/amazonlinux/amazonlinux:2023.7.20250414.0-minimal
  - Using Amazon Linux 2023 minimal image
  - Using `dnf` as package manager

## Software Explicitly Installed in DevContainer

### Downloaded via curl command

| Software | Version | Notes |
| --- | ---: | --- |
| actionlint | 1.7.7 | Linter for GitHub Actions |
| awscli | 2.27.2 | AWS CLI |
| ghalint | 1.3.0 | Linter for GitHub Actions |
| hadolint | 2.12.0 | Linter for Dockerfile |
| shellcheck | 0.10.0 | Linter for Bash |

### Installed via npm command

| Software | Version | Notes |
| --- | ---: | --- |
| markdownlint-cli2 | 0.17.2 | Linter for Markdown |
| npm | 10.9.2 | Node.js package manager |
| SecretLint | 9.3.1 | Secret detection tool |

### Installed via pipx command

| Software | Version | Notes |
| --- | ---: | --- |
| cfn-lint | 1.34.1 | Linter for CloudFormation |
| yamllint | 1.37.0 | Linter for YAML |

### Installed via dnf command

| Package Name | Version | Notes |
| --- | ---: | --- |
| findutils | 4.8.0 | File search utilities |
| git | 2.47.1 | Git command |
| glibc-locale-source | 2.34 | Source for generating locale data |
| nodejs | 18.20.6 | Node.js runtime |
| nodejs-npm | 10.8.2 | Node.js package manager (standard npm package manager) |
| python3.12 | 3.12.9 | Python 3.12 |
| python3.12-pip | 23.2.1 | pip for Python 3.12 |
| tar | 1.34 | Archive tool |
| unzip | 6.0 | Decompression tool |
| xz | 5.2.5 | Compression tool |

## VS Code Extensions Used in DevContainer

| Extension | Version | Notes |
| --- | ---: | --- |
| amazonwebservices.aws-toolkit-vscode | 3.53.0 | AWS extension |
| aws-scripting-guy.cform | 0.0.24 | CloudFormation extension |
| DavidAnson.vscode-markdownlint | 0.59.0 | Linter for Markdown |
| exiasr.hadolint | 1.1.2 | Linter for Dockerfile |
| github.vscode-github-actions | 0.27.1 | GitHub Actions extension |
| github.copilot | 1.297.0 | GitHub Copilot extension |
| github.copilot-chat | 0.26.2 | GitHub Copilot Chat extension |
| kddejong.vscode-cfn-lint | 0.26.4 | Linter for CloudFormation |
| mechatroner.rainbow-csv | 3.19.0 | CSV extension |
| ms-ceintl.vscode-language-pack-ja | 1.99.2025040209 | Japanese language extension |
| redhat.vscode-yaml | 1.17.0 | YAML extension |
| timonwong.shellcheck | 0.37.3 | Linter for Bash |

## Setup Instructions

Install the Dev Containers extension in VS Code and restart VS Code.

```bash
code --install-extension ms-vscode-remote.remote-containers
```

(When using WSL2 on Windows)  
In the Dev Containers extension settings (@ext:ms-vscode-remote.remote-containers), check "Execute In WSL".  

![Open a Remote Window](./images/VSCode_image_01.png)  

Download the repository.  
Open the downloaded folder in VS Code.  
Click "Open a Remote Window" in the bottom left corner of VS Code.

![Open a Remote Window](./images/VSCode_image_02.png)

Click "Reopen in Container".

![Reopen in Container](./images/VSCode_image_03.png)
