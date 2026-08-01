import pytest

from nobitex_bot.security.key_storage import SecretStore, WrongMasterPasswordError


def test_set_and_get_secret_roundtrip(tmp_path):
    store = SecretStore(tmp_path / "secrets.enc", "correct-password")
    store.set_secret("nobitex_api_token", "abc123")

    reloaded = SecretStore(tmp_path / "secrets.enc", "correct-password")
    assert reloaded.get_secret("nobitex_api_token") == "abc123"


def test_wrong_master_password_raises(tmp_path):
    store = SecretStore(tmp_path / "secrets.enc", "correct-password")
    store.set_secret("x", "y")

    wrong_store = SecretStore(tmp_path / "secrets.enc", "wrong-password")
    with pytest.raises(WrongMasterPasswordError):
        wrong_store.get_secret("x")


def test_delete_secret(tmp_path):
    store = SecretStore(tmp_path / "secrets.enc", "pw")
    store.set_secret("a", "1")
    store.set_secret("b", "2")

    store.delete_secret("a")

    assert store.get_secret("a") is None
    assert store.get_secret("b") == "2"
    assert store.list_secret_names() == ["b"]


def test_get_secret_missing_file_returns_none(tmp_path):
    store = SecretStore(tmp_path / "does_not_exist.enc", "pw")
    assert store.get_secret("anything") is None
