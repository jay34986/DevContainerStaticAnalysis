# ビルドステージ 
FROM public.ecr.aws/amazonlinux/amazonlinux:2023.7.20250414.0-minimal AS builder

# シェルオプションの設定
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# バイナリツールのダウンロードとインストール用のディレクトリ作成
WORKDIR /tmp/tools

# ビルドに必要なツールのインストール
RUN dnf update -y && \
    dnf install -y \
    tar-1.34 \
    unzip-6.0 \
    xz-5.2.5 && \
    dnf clean all

# actionlintのダウンロード
RUN curl -L "https://github.com/rhysd/actionlint/releases/download/v1.7.7/actionlint_1.7.7_linux_arm64.tar.gz" | tar xvz

# ghalintのダウンロード
RUN curl -L "https://github.com/suzuki-shunsuke/ghalint/releases/download/v1.3.0/ghalint_1.3.0_linux_arm64.tar.gz" | tar xvz

# hadolintのダウンロード
RUN curl -L "https://github.com/hadolint/hadolint/releases/download/v2.12.0/hadolint-Linux-arm64" -o hadolint && \
    chmod +x hadolint

# shellcheckのダウンロード
RUN curl -L "https://github.com/koalaman/shellcheck/releases/download/v0.8.0/shellcheck-v0.8.0.linux.aarch64.tar.xz" | tar xJv

# 実行環境
FROM public.ecr.aws/amazonlinux/amazonlinux:2023.7.20250414.0-minimal

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
COPY --from=builder /tmp/tools/shellcheck-v0.8.0/shellcheck /usr/local/bin/

# 開発に必要な基本ツールのインストール
RUN dnf update -y && \
    dnf install -y \
    findutils-4.8.0 \
    git-2.40.1 \
    glibc-locale-source-2.34 \
    nodejs-18.20.6 \
    nodejs-npm-10.8.2 \
    python3.12-3.12.9 \
    python3.12-pip-23.2.1 \
    tar-1.34 \
    unzip-6.0 \
    xz-5.2.5 && \
    dnf clean all

# localeの追加
RUN localedef -i en_US -f UTF-8 en_US.UTF-8

# AWS CLIのダウンロードとインストール
RUN curl "https://awscli.amazonaws.com/awscli-exe-linux-aarch64-2.26.4.zip" -o "awscliv2.zip" && \
    unzip awscliv2.zip && \
    ./aws/install --bin-dir /usr/local/bin --install-dir /usr/local/aws-cli && \
    chmod +x /usr/local/bin/aws* && \
    rm -rf awscliv2.zip aws

# pipxのインストールと環境設定
RUN python3.12 -m pip install --no-cache-dir pipx==1.7.1 && \
    python3.12 -m pip install --no-cache-dir setuptools==70.0.0 && \
    python3.12 -m pipx ensurepath

# Python関連ツールのインストール
RUN pipx install cfn-lint==1.34.1 && \
    pipx install yamllint==1.37.0 && \
    rm -rf /root/.local/pipx/logs/*

# NPMパッケージのインストール（runtimeステージで実行）
RUN npm install -g --omit=dev --no-progress markdownlint-cli2@0.17.2 && \
    npm install -g --omit=dev --no-progress secretlint@9.3.1 @secretlint/secretlint-rule-preset-recommend@9.3.1
