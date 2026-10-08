import httpx
import pytest

from meu_danfe.cli.download import main


def _ok_handler(request: httpx.Request) -> httpx.Response:
    if "fd/add" in request.url.path:
        return httpx.Response(200, json={"status": "OK"})
    return httpx.Response(200, json={"name": "nota.xml", "type": "NFE", "format": "XML", "data": "<x/>"})


def test_main_requires_key_or_file(capsys) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main([])
    assert excinfo.value.code == 2


def test_save_writes_file_and_reports_exit_zero(tmp_path, monkeypatch) -> None:
    import meu_danfe.cli.download as download_mod
    from meu_danfe.client import MeuDanfeAsyncClient as RealAsyncClient

    # Capture the real class under a different name before patching: a
    # lambda that calls `download_mod.MeuDanfeAsyncClient` from inside its
    # own body would resolve to itself (late-binding on the module global)
    # and recurse forever once the attribute is replaced.
    monkeypatch.setattr(
        download_mod, "MeuDanfeAsyncClient",
        lambda *a, **kw: RealAsyncClient(*a, **{**kw, "transport": httpx.MockTransport(_ok_handler)}),
    )
    monkeypatch.setenv("MEU_DANFE_API_KEY", "chave-de-teste")
    key = "6" * 44  # must be 44 digits — the client now validates access keys
    rc = main(["--key", key, "--save", "--out", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "nota.xml").read_text(encoding="utf-8") == "<x/>"


def test_exclude_existing_in_skips_already_downloaded_keys(tmp_path, monkeypatch, capsys) -> None:
    # The filtered key list ends up empty, so _run's `if keys:` guard never
    # constructs a client — no transport mocking needed, just a valid config.
    # Must be a real 44-DIGIT key: existing_keys_in_dir only recognizes
    # digits (ACCESS_KEY_RE), so a letter-based placeholder like "k" * 44
    # would never match and the exclusion filter would silently do nothing.
    key = "9" * 44
    (tmp_path / f"NFE-{key}.xml").write_text("<x/>", encoding="utf-8")
    monkeypatch.setenv("MEU_DANFE_API_KEY", "chave-de-teste")
    rc = main(["--key", key, "--exclude-existing-in", str(tmp_path)])
    out = capsys.readouterr().out
    assert "0 ok, 0 falhas" in out
    assert rc == 0


def test_env_file_in_cwd_is_used_automatically_without_env_file_flag(tmp_path, monkeypatch) -> None:
    # README/CLAUDE.md tell a user to "copy .env.example to .env" and then
    # just run `uv run meu-danfe --key ...` — no --env-file flag. Without
    # reading ./.env by default, that documented flow fails.
    pytest.importorskip("dotenv")
    monkeypatch.delenv("MEU_DANFE_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("MEU_DANFE_API_KEY=da-dotenv\n", encoding="utf-8")
    key = "9" * 44
    (tmp_path / f"NFE-{key}.xml").write_text("<x/>", encoding="utf-8")
    # Reuses the "filtered list ends up empty" path from the test above so
    # no transport mocking is needed — this test only proves the config
    # built successfully from ./.env (no ConfigurationError exit code).
    rc = main(["--key", key, "--exclude-existing-in", str(tmp_path)])
    assert rc == 0
