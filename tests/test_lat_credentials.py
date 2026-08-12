from datetime import datetime

import pytest

from lat5.lat_credentials import CredentialsError, load_credentials


def test_load_credentials_reads_lat_names_without_exposing_values(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "LAT5_KIWOOM_APPKEY=app-value\nLAT5_KIWOOM_SECRETKEY=secret-value\n",
        encoding="utf-8",
    )

    credentials = load_credentials(env)

    assert credentials.appkey == "app-value"
    assert credentials.secretkey == "secret-value"
    assert "app-value" not in repr(credentials)
    assert "secret-value" not in repr(credentials)


def test_load_credentials_rejects_missing_or_placeholder_values(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "LAT5_KIWOOM_APPKEY=받은_APP_KEY\nLAT5_KIWOOM_SECRETKEY=\n",
        encoding="utf-8",
    )

    with pytest.raises(CredentialsError):
        load_credentials(env)
