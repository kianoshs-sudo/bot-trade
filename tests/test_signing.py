import base64

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from nobitex_bot.exchange.signing import sign_request


def _urlsafe_b64_no_padding(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def test_sign_request_produces_signature_verifiable_by_public_key():
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    raw_private = private_key.private_bytes_raw()
    private_key_b64 = _urlsafe_b64_no_padding(raw_private)

    signature_b64 = sign_request(private_key_b64, 1700000000, "POST", "/market/orders/add", '{"a":1}')

    signature = base64.b64decode(signature_b64)
    message = b"1700000000POST/market/orders/add" + b'{"a":1}'
    public_key.verify(signature, message)  # می‌ترکه اگه امضا غلط باشه


def test_sign_request_is_deterministic_for_same_input():
    private_key = Ed25519PrivateKey.generate()
    private_key_b64 = _urlsafe_b64_no_padding(private_key.private_bytes_raw())

    sig1 = sign_request(private_key_b64, 123, "GET", "/market/orders/list", "")
    sig2 = sign_request(private_key_b64, 123, "GET", "/market/orders/list", "")

    assert sig1 == sig2


def test_sign_request_changes_with_different_timestamp():
    private_key = Ed25519PrivateKey.generate()
    private_key_b64 = _urlsafe_b64_no_padding(private_key.private_bytes_raw())

    sig1 = sign_request(private_key_b64, 123, "GET", "/x", "")
    sig2 = sign_request(private_key_b64, 456, "GET", "/x", "")

    assert sig1 != sig2


def test_sign_request_accepts_padded_and_unpadded_base64():
    private_key = Ed25519PrivateKey.generate()
    raw = private_key.private_bytes_raw()
    padded = base64.urlsafe_b64encode(raw).decode("utf-8")
    unpadded = padded.rstrip("=")

    assert sign_request(padded, 1, "GET", "/x", "") == sign_request(unpadded, 1, "GET", "/x", "")
