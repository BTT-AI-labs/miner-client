from __future__ import annotations

import base64
import hashlib

import base58


def ed25519_public_key_to_peer_id(public_key_bytes: bytes) -> str:
    # PublicKey protobuf: field 1(type=Ed25519=1), field 2(data=<32-byte key>)
    protobuf = b"\x08\x01\x12\x20" + public_key_bytes
    multihash_identity = b"\x00" + bytes([len(protobuf)]) + protobuf
    return base58.b58encode(multihash_identity).decode("ascii")


def build_challenge_message(
    node_public_key: str,
    challenge_id: str,
    nonce: str,
    purpose: str,
    expires_at: int | str,
) -> str:
    return f"{node_public_key}:{challenge_id}:{nonce}:{purpose}:{expires_at}"


def build_challenge_digest(
    node_public_key: str,
    challenge_id: str,
    nonce: str,
    purpose: str,
    expires_at: int | str,
) -> bytes:
    message = build_challenge_message(node_public_key, challenge_id, nonce, purpose, expires_at)
    return hashlib.sha256(message.encode("utf-8")).digest()


def encode_signature(signature: bytes) -> str:
    return base64.b64encode(signature).decode("ascii")
