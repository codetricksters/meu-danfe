"""The single most important regression test in this plan: importing the
package, and building a config without one, must never raise KeyError —
the exact bug app.py has today at module scope."""
import importlib

import pytest


def test_import_does_not_touch_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("MEU_DANFE_API_KEY", "MEU_DANFE_API_URL"):
        monkeypatch.delenv(name, raising=False)
    import meu_danfe
    importlib.reload(meu_danfe)  # a fresh import must not raise


def test_from_env_raises_configuration_error_not_keyerror() -> None:
    from meu_danfe.config import MeuDanfeConfig
    from meu_danfe.exceptions import ConfigurationError

    with pytest.raises(ConfigurationError):
        MeuDanfeConfig.from_env(env={})
