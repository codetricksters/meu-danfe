def test_documented_public_names_are_importable() -> None:
    import meu_danfe

    for name in (
        "MeuDanfeAsyncClient", "MeuDanfeClient", "MeuDanfeConfig", "DocumentStatus",
        "AddResult", "XmlDocument", "FetchResult", "MeuDanfeError",
        "ConfigurationError", "DocumentUnavailableError", "NotFoundStatusError",
        "SearchFailedError", "PollTimeoutError", "TransportError",
        "MalformedResponseError", "InvalidAccessKeyError", "MissingDependencyError",
        "MeuDanfeAPIError", "AuthenticationError", "InsufficientBalanceError",
        "ApiKeyReplacedError", "InvalidKeyResponseError", "DocumentNotFoundError",
        "DownloadRequestError", "UnexpectedStatusError",
    ):
        assert hasattr(meu_danfe, name), f"missing public export: {name}"
        assert name in meu_danfe.__all__
