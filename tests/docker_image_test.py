"""Test module for verifying the Docker image configuration and installed tools."""

import subprocess

import pytest
import testinfra
from testinfra.host import Host


@pytest.fixture(scope="session")
def host() -> Host:
    """Create a Docker container for testing and yield the host object."""
    image_name = "dev-container:test"
    docker_bin = "/usr/bin/docker"
    # コンテナが既に存在しているか確認し、なければ起動
    docker_id = (
        subprocess.check_output(  # noqa: S603
            [
                docker_bin,
                "run",
                "-d",
                "--rm",  # テスト終了後に自動削除
                image_name,
                "sleep",
                "600",  # テスト中にコンテナが終了しないようにする
            ],
        )
        .decode()
        .strip()
    )
    try:
        yield testinfra.get_host("docker://" + docker_id)
    finally:
        # テスト後に必ずコンテナを削除
        subprocess.call([docker_bin, "rm", "-f", docker_id])  # noqa: S603


def test_actionlint_is_installed(host: Host) -> None:
    """Test if actionlint is installed and has the correct version."""
    cmd = host.run("actionlint --version")
    assert cmd.rc == 0  # noqa: S101
    assert "1.7.7" in cmd.stdout  # noqa: S101


def test_ghalint_is_installed(host: Host) -> None:
    """Test if ghalint is installed and has the correct version."""
    cmd = host.run("ghalint -v")
    assert cmd.rc == 0  # noqa: S101
    assert "1.3.0" in cmd.stdout  # noqa: S101


def test_hadolint_is_installed(host: Host) -> None:
    """Test if hadolint is installed and has the correct version."""
    cmd = host.run("hadolint --version")
    assert cmd.rc == 0  # noqa: S101
    assert "2.12.0" in cmd.stdout  # noqa: S101


def test_shellcheck_is_installed(host: Host) -> None:
    """Test if shellcheck is installed and has the correct version."""
    cmd = host.run("shellcheck --version")
    assert cmd.rc == 0  # noqa: S101
    assert "0.10.0" in cmd.stdout  # noqa: S101


def test_aws_cli_is_installed(host: Host) -> None:
    """Test if AWS CLI is installed and has the correct version."""
    cmd = host.run("aws --version")
    assert cmd.rc == 0  # noqa: S101
    assert "2.27.2" in cmd.stdout  # noqa: S101


def test_cfn_lint_is_installed(host: Host) -> None:
    """Test if cfn-lint is installed and has the correct version."""
    cmd = host.run("cfn-lint --version")
    assert cmd.rc == 0  # noqa: S101
    assert "1.34.1" in cmd.stdout  # noqa: S101


def test_yamllint_is_installed(host: Host) -> None:
    """Test if yamllint is installed and has the correct version."""
    cmd = host.run("yamllint --version")
    assert cmd.rc == 0  # noqa: S101
    assert "1.37.0" in cmd.stdout  # noqa: S101


def test_markdownlint_is_installed(host: Host) -> None:
    """Test if markdownlint is installed and has the correct version."""
    cmd = host.run("markdownlint-cli2 --version")
    assert cmd.rc == 0  # noqa: S101
    assert "0.17.2" in cmd.stdout  # noqa: S101


def test_secretlint_is_installed(host: Host) -> None:
    """Test if secretlint is installed and has the correct version."""
    cmd = host.run("secretlint --version")
    assert cmd.rc == 0  # noqa: S101
    assert "9.3.1" in cmd.stdout  # noqa: S101


FILE_MODE_EXECUTABLE = 0o755


def test_binaries_exist(host: Host) -> None:
    """Test if the required binaries exist and have the correct permissions."""
    binaries = [
        "/usr/local/bin/actionlint",
        "/usr/local/bin/ghalint",
        "/usr/local/bin/hadolint",
        "/usr/local/bin/shellcheck",
        "/usr/local/bin/aws",
    ]
    for binary in binaries:
        assert host.file(binary).exists  # noqa: S101
        assert host.file(binary).mode == FILE_MODE_EXECUTABLE  # noqa: S101
