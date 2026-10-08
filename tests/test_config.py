from pathlib import Path

import pytest

from meu_danfe.config import DEFAULT_BASE_URL, MeuDanfeConfig, default_dotenv_path
from meu_danfe.exceptions import ConfigurationError


def test_explicit_api_key_requires_no_environment() -> None:
    config = MeuDanfeConfig(api_key="minha-chave")
    assert config.base_url == DEFAULT_BASE_URL
    assert config.min_key_interval == 1.0


def test_blank_api_key_raises_configuration_error() -> None:
    with pytest.raises(ConfigurationError):
        MeuDanfeConfig(api_key="")


def test_base_url_without_trailing_slash_gets_one() -> None:
    config = MeuDanfeConfig(api_key="x", base_url="https://api.meudanfe.com.br/v2")
    assert config.base_url == "https://api.meudanfe.com.br/v2/"


def test_min_key_interval_below_one_second_rejected_by_default() -> None:
    with pytest.raises(ConfigurationError):
        MeuDanfeConfig(api_key="x", min_key_interval=0.1)


def test_min_key_interval_below_one_second_allowed_when_opted_in() -> None:
    config = MeuDanfeConfig(api_key="x", min_key_interval=0.1, allow_unsafe_interval=True)
    assert config.min_key_interval == 0.1


def test_repr_masks_api_key() -> None:
    config = MeuDanfeConfig(api_key="segredo-super-secreto")
    assert "segredo-super-secreto" not in repr(config)
    assert "reto" in repr(config)  # last 4 chars kept for operator disambiguation


def test_from_env_reads_prefixed_variables() -> None:
    env = {"MEU_DANFE_API_KEY": "chave-do-ambiente", "MEU_DANFE_API_URL": "https://example.test/v2/"}
    config = MeuDanfeConfig.from_env(env=env)
    assert config.api_key == "chave-do-ambiente"
    assert config.base_url == "https://example.test/v2/"


def test_from_env_explicit_api_key_overrides_environment() -> None:
    config = MeuDanfeConfig.from_env(env={"MEU_DANFE_API_KEY": "do-ambiente"}, api_key="explicita")
    assert config.api_key == "explicita"


def test_from_env_without_dotenv_path_never_imports_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys
    monkeypatch.setitem(sys.modules, "dotenv", None)  # import dotenv would now raise
    config = MeuDanfeConfig.from_env(env={"MEU_DANFE_API_KEY": "x"})
    assert config.api_key == "x"


def test_default_dotenv_path_returns_env_file_in_cwd_when_present(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("MEU_DANFE_API_KEY=x\n", encoding="utf-8")
    assert default_dotenv_path() == Path(".env")


def test_default_dotenv_path_is_none_when_no_env_file_present(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert default_dotenv_path() is None


def test_from_env_reads_api_key_from_dotenv_path(tmp_path) -> None:
    pytest.importorskip("dotenv")
    env_file = tmp_path / ".env"
    env_file.write_text("MEU_DANFE_API_KEY=da-dotenv\n", encoding="utf-8")
    config = MeuDanfeConfig.from_env(env={}, dotenv_path=env_file)
    assert config.api_key == "da-dotenv"
