from cryptography.fernet import Fernet

from app.providers.openai_compatible import thinking_request_options
from app.schemas.managed_model import ManagedModelCreate, normalized_base_url
from app.security.credentials import CredentialCipher, CredentialDecryptionError
from app.services.managed_model_service import make_model_uid


def test_credential_cipher_never_stores_plaintext_and_rejects_wrong_key() -> None:
    secret = "sk-private-value-ABCD"
    cipher = CredentialCipher(Fernet.generate_key().decode())
    encrypted = cipher.encrypt(secret)

    assert secret not in encrypted
    assert cipher.decrypt(encrypted) == secret

    wrong_cipher = CredentialCipher(Fernet.generate_key().decode())
    try:
        wrong_cipher.decrypt(encrypted)
    except CredentialDecryptionError:
        pass
    else:
        raise AssertionError("a different master key must not decrypt the credential")


def test_model_identity_normalizes_endpoint_but_excludes_secret_and_parameters() -> None:
    first = ManagedModelCreate(
        display_name="Qwen Plus",
        base_url="HTTPS://Example.COM:443/v1/",
        api_key="first-secret",
        model_name="qwen-plus",
        temperature=0.1,
    )
    second = ManagedModelCreate(
        display_name="Renamed",
        base_url="https://example.com/v1",
        api_key="replacement-secret",
        model_name="qwen-plus",
        temperature=1.2,
    )

    assert normalized_base_url(first.base_url) == "https://example.com/v1"
    assert make_model_uid(first.base_url, first.model_name) == make_model_uid(
        second.base_url, second.model_name
    )
    assert make_model_uid(first.base_url, first.model_name).startswith("mdl_")


def test_openai_compatible_model_creation_does_not_require_a_provider_vendor() -> None:
    model = ManagedModelCreate(
        display_name="DeepSeek Chat",
        base_url="https://api.deepseek.com",
        api_key="secret",
        model_name="deepseek-chat",
    )

    assert model.base_url == "https://api.deepseek.com"
    assert model.model_name == "deepseek-chat"
    assert model.enable_thinking is False
    assert "provider" not in model.model_dump()


def test_thinking_setting_is_translated_only_for_qwen_models() -> None:
    assert thinking_request_options("qwen3.7-plus", False) == {
        "extra_body": {"enable_thinking": False}
    }
    assert thinking_request_options("Qwen/Qwen3-32B", True) == {
        "extra_body": {"enable_thinking": True}
    }
    assert thinking_request_options("deepseek-v4-flash-0731", False) == {
        "extra_body": {"enable_thinking": False}
    }
    assert thinking_request_options("deepseek-chat", False) == {}
