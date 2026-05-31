# ビルドステージ
FROM public.ecr.aws/amazonlinux/amazonlinux:2023.11.20260526.0-minimal AS builder

# シェルオプションの設定
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# バイナリツールのダウンロードとインストール用のディレクトリ作成
WORKDIR /tmp/tools

# ビルドに必要なツールのインストール
RUN dnf update -y && \
    dnf install -y \
    gzip-1.12 \
    tar-1.34 \
    unzip-6.0 \
    xz-5.2.5 && \
    dnf clean all

# actionlintのダウンロード
ARG ACTIONLINT_VERSION=1.7.12
RUN BUILDARCH=$(uname -m) && \
    if [ "${BUILDARCH}" = "x86_64" ]; then \
        curl -LO "https://github.com/rhysd/actionlint/releases/download/v${ACTIONLINT_VERSION}/actionlint_${ACTIONLINT_VERSION}_linux_amd64.tar.gz" && \
        tar xvzf actionlint_${ACTIONLINT_VERSION}_linux_amd64.tar.gz; \
    elif [ "${BUILDARCH}" = "aarch64" ]; then \
        curl -LO "https://github.com/rhysd/actionlint/releases/download/v${ACTIONLINT_VERSION}/actionlint_${ACTIONLINT_VERSION}_linux_arm64.tar.gz" && \
        tar xvzf actionlint_${ACTIONLINT_VERSION}_linux_arm64.tar.gz; \
    else \
        echo "actionlint: Unsupported architecture: ${BUILDARCH}"; exit 1; \
    fi

# ghalintのダウンロード
ARG GHALINT_VERSION=1.5.6
RUN BUILDARCH=$(uname -m) && \
    if [ "${BUILDARCH}" = "x86_64" ]; then \
        curl -LO "https://github.com/suzuki-shunsuke/ghalint/releases/download/v${GHALINT_VERSION}/ghalint_${GHALINT_VERSION}_linux_amd64.tar.gz" && \
        tar xvzf ghalint_${GHALINT_VERSION}_linux_amd64.tar.gz; \
    elif [ "${BUILDARCH}" = "aarch64" ]; then \
        curl -LO "https://github.com/suzuki-shunsuke/ghalint/releases/download/v${GHALINT_VERSION}/ghalint_${GHALINT_VERSION}_linux_arm64.tar.gz" && \
        tar xvzf ghalint_${GHALINT_VERSION}_linux_arm64.tar.gz; \
    else \
        echo "ghalint: Unsupported architecture: ${BUILDARCH}"; exit 1; \
    fi

# hadolintのダウンロード
ARG HADOLINT_VERSION=2.14.0
RUN BUILDARCH=$(uname -m) && \
    if [ "${BUILDARCH}" = "x86_64" ]; then \
        curl -L "https://github.com/hadolint/hadolint/releases/download/v${HADOLINT_VERSION}/hadolint-Linux-x86_64" -o hadolint; \
    elif [ "${BUILDARCH}" = "aarch64" ]; then \
        curl -L "https://github.com/hadolint/hadolint/releases/download/v${HADOLINT_VERSION}/hadolint-Linux-arm64" -o hadolint; \
    else \
        echo "hadolint: Unsupported architecture: ${BUILDARCH}"; exit 1; \
    fi && \
    chmod +x hadolint

# shellcheckのダウンロード
ARG SHELLCHECK_VERSION=0.11.0
RUN BUILDARCH=$(uname -m) && \
    if [ "${BUILDARCH}" = "x86_64" ]; then \
        curl -LO "https://github.com/koalaman/shellcheck/releases/download/v${SHELLCHECK_VERSION}/shellcheck-v${SHELLCHECK_VERSION}.linux.x86_64.tar.xz" && \
        tar xJvf shellcheck-v${SHELLCHECK_VERSION}.linux.x86_64.tar.xz; \
    elif [ "${BUILDARCH}" = "aarch64" ]; then \
        curl -LO "https://github.com/koalaman/shellcheck/releases/download/v${SHELLCHECK_VERSION}/shellcheck-v${SHELLCHECK_VERSION}.linux.aarch64.tar.xz" && \
        tar xJvf shellcheck-v${SHELLCHECK_VERSION}.linux.aarch64.tar.xz; \
    else \
        echo "shellcheck: Unsupported architecture: ${BUILDARCH}"; exit 1; \
    fi

# 実行環境
FROM public.ecr.aws/amazonlinux/amazonlinux:2023.11.20260526.0-minimal

# シェルオプションの設定
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# 環境変数の設定
# hadolint ignore=SC2028
RUN echo 'export PS1="[\u@\h \w]\\$ "' >> /root/.bashrc

# 環境変数の設定
ENV PATH="/root/.local/bin:/usr/local/bin:$PATH"

# バイナリのコピー
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /tmp/tools/actionlint /usr/local/bin/
COPY --from=builder /tmp/tools/ghalint /usr/local/bin/
COPY --from=builder /tmp/tools/hadolint /usr/local/bin/
COPY --from=builder /tmp/tools/shellcheck-v0.11.0/shellcheck /usr/local/bin/

# 開発に必要な基本ツールのインストール
RUN dnf update -y && \
    dnf --releasever=latest install -y \
    diffutils-3.8 \
    findutils-4.8.0 \
    git-2.50.1 \
    glibc-locale-source-2.34 \
    gzip-1.12 \
    nodejs24-24.15.0 \
    nodejs24-npm-11.12.1 \
    python3.14-3.14.4 \
    python3.14-pip-25.1.1 \
    tar-1.34 \
    tree-1.8.0 \
    unzip-6.0 \
    which-2.21 \
    xz-5.2.5 && \
    dnf clean all

# localeの追加
RUN localedef -i en_US -f UTF-8 en_US.UTF-8

# AWS CLIのダウンロードとインストール
ARG AWSCLI_VERSION=2.34.57
RUN BUILDARCH=$(uname -m) && \
    if [ "${BUILDARCH}" = "x86_64" ]; then \
        curl -L "https://awscli.amazonaws.com/awscli-exe-linux-x86_64-${AWSCLI_VERSION}.zip" -o awscliv2.zip; \
    elif [ "${BUILDARCH}" = "aarch64" ]; then \
        curl -L "https://awscli.amazonaws.com/awscli-exe-linux-aarch64-${AWSCLI_VERSION}.zip" -o awscliv2.zip; \
    else \
        echo "AWS CLI: Unsupported architecture: ${BUILDARCH}"; exit 1; \
    fi && \
    unzip awscliv2.zip && \
    ./aws/install --bin-dir /usr/local/bin --install-dir /usr/local/aws-cli && \
    chmod +x /usr/local/bin/aws* && \
    rm -rf awscliv2.zip aws

# Pythonパッケージのインストール
COPY .devcontainer/bootstrap-requirements.txt /tmp/bootstrap-requirements.txt
COPY .devcontainer/requirements.txt /tmp/requirements.txt
# hadolint ignore=DL3013
RUN python3.14 -m pip install --no-cache-dir --requirement /tmp/bootstrap-requirements.txt && \
    while IFS= read -r package; do \
        [[ -z "${package}" || "${package}" =~ ^# ]] && continue; \
        pipx install --python python3.14 --pip-args=--no-cache-dir "${package}"; \
    done < /tmp/requirements.txt && \
    rm /tmp/bootstrap-requirements.txt /tmp/requirements.txt

# NPMパッケージのインストール
COPY .devcontainer/package.json /opt/node/package.json
WORKDIR /opt/node
RUN npm install --omit=dev --no-progress && \
    npm cache clean --force && \
    rm -rf /root/.npm/_logs
WORKDIR /

ENV PATH="/opt/node/node_modules/.bin:${PATH}"
