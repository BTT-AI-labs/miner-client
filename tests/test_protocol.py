from __future__ import annotations

from miner_agent.protocol import build_tosign_digest, ed25519_public_key_to_peer_id


def test_ed25519_public_key_to_peer_id_matches_libp2p_prefix() -> None:
    public_key = bytes.fromhex("11" * 32)

    peer_id = ed25519_public_key_to_peer_id(public_key)

    assert peer_id.startswith("12D3KooW")


def test_build_challenge_digest_is_stable() -> None:
    digest = build_tosign_digest(
        {
            "node_id": "abcd",
            "challenge_id": "chl_123",
            "nonce": "deadbeef",
            "purpose": "register",
            "expires_at": 1710000060,
        }
    )

    assert digest.hex() == "6bbe910a45527826e5e1df2f6fc69e0d24c7fb8f2aff2b82dc7bc39d0a9a81ef"
