from __future__ import annotations

from pathlib import Path

from miner_agent.identity import IdentityManager


def test_identity_manager_persists_and_reloads_identity(tmp_path: Path) -> None:
    manager = IdentityManager(tmp_path)

    identity = manager.ensure_identity()
    reloaded = manager.load_identity()

    assert manager.config_path.exists()
    assert identity.node_id == reloaded.node_id
    assert identity.wallet_address == reloaded.wallet_address
    assert reloaded.public_dict()["node_id"] == identity.node_id
    assert "node_private_key" not in reloaded.public_dict()


def test_sign_challenge_returns_verifiable_signature(tmp_path: Path) -> None:
    manager = IdentityManager(tmp_path)
    identity = manager.ensure_identity()
    digest = b"challenge-digest"

    signature = manager.sign(identity, digest)

    assert isinstance(signature, bytes)
    assert signature
