"""Tests for shade.cli module."""

import yaml
from click.testing import CliRunner

from shade.cli import cli


def _setup_project(tmp_path, shade_config: dict, compose: dict):
    """Create shade.yml and docker-compose.yml in a temp directory."""
    shade_yml = tmp_path / "shade.yml"
    with open(shade_yml, "w") as f:
        yaml.dump(shade_config, f)

    compose_yml = tmp_path / "docker-compose.yml"
    with open(compose_yml, "w") as f:
        yaml.dump(compose, f)

    return tmp_path


class TestBuildCommand:
    """Test the 'shade build' CLI command."""

    def test_build_success(self, tmp_path):
        _setup_project(
            tmp_path,
            shade_config={"app": {"name": "my-app"}, "cvm": {"domain": "example.com"}},
            compose={"services": {"my-app": {"image": "python:3.11"}}},
        )
        runner = CliRunner()
        output_path = str(tmp_path / "docker-compose.shade.yml")
        result = runner.invoke(
            cli,
            [
                "build",
                "-c",
                str(tmp_path / "shade.yml"),
                "-f",
                str(tmp_path / "docker-compose.yml"),
                "-o",
                output_path,
            ],
        )
        assert result.exit_code == 0
        assert "Generated" in result.output

    def test_build_validation_error(self, tmp_path):
        _setup_project(
            tmp_path,
            shade_config={"app": {"name": "my-app"}, "cvm": {"domain": "example.com"}},
            compose={"services": {"wrong": {"image": "python:3.11"}}},
        )
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "build",
                "-c",
                str(tmp_path / "shade.yml"),
                "-f",
                str(tmp_path / "docker-compose.yml"),
                "-o",
                str(tmp_path / "out.yml"),
            ],
        )
        assert result.exit_code == 1
        assert "Error" in result.output


class TestValidateCommand:
    """Test the 'shade validate' CLI command."""

    def test_validate_success(self, tmp_path):
        _setup_project(
            tmp_path,
            shade_config={"app": {"name": "my-app"}, "cvm": {"domain": "example.com"}},
            compose={"services": {"my-app": {"image": "python:3.11"}}},
        )
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "validate",
                "-c",
                str(tmp_path / "shade.yml"),
                "-f",
                str(tmp_path / "docker-compose.yml"),
            ],
        )
        assert result.exit_code == 0
        assert "valid" in result.output.lower()

    def test_validate_errors(self, tmp_path):
        _setup_project(
            tmp_path,
            shade_config={"app": {"name": "my-app"}, "cvm": {"domain": "example.com"}},
            compose={"services": {"wrong": {"image": "python:3.11"}}},
        )
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "validate",
                "-c",
                str(tmp_path / "shade.yml"),
                "-f",
                str(tmp_path / "docker-compose.yml"),
            ],
        )
        assert result.exit_code == 1


class TestInitCommand:
    """Test the 'shade init' CLI command."""

    def test_init_success(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(cli, ["init", "-d", str(tmp_path)])
        assert result.exit_code == 0
        assert "Created" in result.output
        assert (tmp_path / "shade.yml").exists()

    def test_init_already_exists(self, tmp_path):
        (tmp_path / "shade.yml").write_text("existing")
        runner = CliRunner()
        result = runner.invoke(cli, ["init", "-d", str(tmp_path)])
        assert result.exit_code == 1
        assert "Error" in result.output
