from __future__ import annotations

from miner_agent.protocol import build_challenge_digest, ed25519_public_key_to_peer_id


def test_ed25519_public_key_to_peer_id_matches_libp2p_prefix() -> None:
    public_key = bytes.fromhex("11" * 32)

    peer_id = ed25519_public_key_to_peer_id(public_key)

    assert peer_id.startswith("12D3KooW")


def test_build_challenge_digest_is_stable() -> None:
    digest = build_challenge_digest(
        "abcd",
        "chl_123",
        "deadbeef",
        "register",
        1710000060,
    )

    assert digest.hex() == "1e217b25741b212d8d1fc96ee7c7d8be8e31e6c8536155a3ecc429868949b13e"
