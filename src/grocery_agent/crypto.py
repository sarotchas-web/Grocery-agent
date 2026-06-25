from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from dataclasses import dataclass


MASTER_KEY_ENV = "GROCERY_AGENT_MASTER_KEY"


class CryptoError(RuntimeError):
    pass


class CryptoProvider:
    def encrypt_json(self, payload: dict) -> str:
        raise NotImplementedError

    def decrypt_json(self, token: str) -> dict:
        raise NotImplementedError


@dataclass(frozen=True)
class EnvMasterKeyCryptoProvider(CryptoProvider):
    key_id: str = "local-env-v1"

    @classmethod
    def from_env(cls) -> "EnvMasterKeyCryptoProvider":
        if not os.environ.get(MASTER_KEY_ENV):
            raise CryptoError(f"{MASTER_KEY_ENV} must be set")
        return cls()

    @property
    def _key(self) -> bytes:
        raw = os.environ.get(MASTER_KEY_ENV)
        if not raw:
            raise CryptoError(f"{MASTER_KEY_ENV} must be set")
        return hashlib.sha256(raw.encode("utf-8")).digest()

    def encrypt_json(self, payload: dict) -> str:
        plaintext = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        nonce = secrets.token_bytes(16)
        keystream = _stream(self._key, nonce, len(plaintext))
        ciphertext = bytes(a ^ b for a, b in zip(plaintext, keystream, strict=True))
        header = {"v": 1, "kid": self.key_id, "n": _b64(nonce), "c": _b64(ciphertext)}
        header_bytes = json.dumps(header, sort_keys=True).encode("utf-8")
        tag = hmac.new(self._key, header_bytes, hashlib.sha256).digest()
        envelope = {"protected": header, "tag": _b64(tag)}
        return base64.urlsafe_b64encode(json.dumps(envelope, sort_keys=True).encode("utf-8")).decode("ascii")

    def decrypt_json(self, token: str) -> dict:
        try:
            envelope = json.loads(base64.urlsafe_b64decode(token.encode("ascii")))
            header = envelope["protected"]
            tag = _unb64(envelope["tag"])
            header_bytes = json.dumps(header, sort_keys=True).encode("utf-8")
        except Exception as exc:
            raise CryptoError("Invalid encrypted profile envelope") from exc
        expected = hmac.new(self._key, header_bytes, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, expected):
            raise CryptoError("Encrypted profile authentication failed")
        nonce = _unb64(header["n"])
        ciphertext = _unb64(header["c"])
        keystream = _stream(self._key, nonce, len(ciphertext))
        plaintext = bytes(a ^ b for a, b in zip(ciphertext, keystream, strict=True))
        return json.loads(plaintext.decode("utf-8"))


def _stream(key: bytes, nonce: bytes, length: int) -> bytes:
    output = bytearray()
    counter = 0
    while len(output) < length:
        block = hmac.new(key, nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest()
        output.extend(block)
        counter += 1
    return bytes(output[:length])


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value.encode("ascii"))
