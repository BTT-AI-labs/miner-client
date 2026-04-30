from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519
from eth_hash.auto import keccak

from .protocol import ed25519_public_key_to_peer_id


@dataclass(frozen=True)
class Identity:
    node_id: str
    node_key_type: str
    node_public_key: str
    node_private_key: str
    wallet_key_type: str
    wallet_public_key: str
    wallet_private_key: str
    wallet_address: str
    created_at: int

    def public_dict(self) -> dict[str, object]:
        return {
            "node_id": self.node_id,
            "node_key_type": self.node_key_type,
            "node_public_key": self.node_public_key,
            "wallet_key_type": self.wallet_key_type,
            "wallet_public_key": self.wallet_public_key,
            "wallet_address": self.wallet_address,
            "created_at": self.created_at,
        }


class IdentityManager:
    def __init__(self, miner_home: Path) -> None:
        self._miner_home = miner_home
        self._config_path = miner_home / "config.json"

    @property
    def config_path(self) -> Path:
        return self._config_path

    def ensure_identity(self) -> Identity:
        if self._config_path.exists():
            return self.load_identity()
        identity = self._generate_identity()
        self.save_identity(identity)
        return identity

    # load local config.json from local fs
    def load_identity(self) -> Identity:
        raw = json.loads(self._config_path.read_text(encoding="utf-8"))
        return Identity(**raw)

    # save config.json into local filesystem.
    def save_identity(self, identity: Identity) -> None:
        self._miner_home.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            self._miner_home.chmod(0o700)
        except OSError:
            pass
        self._config_path.write_text(
            json.dumps(asdict(identity), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        try:
            self._config_path.chmod(0o600)
        except OSError:
            pass

    def sign(self, identity: Identity, digest: bytes) -> bytes:
        private_key = ed25519.Ed25519PrivateKey.from_private_bytes(
            bytes.fromhex(identity.node_private_key)
        )
        return private_key.sign(digest)

    # generate a new node's pubkey & private key, as well as miners'
    # nodes can share one wallet address, while every node must have
    # single different node pubkey & private key
    def _generate_identity(self) -> Identity:
        # node key-pair uses Ed25519 algo
        node_private_key = ed25519.Ed25519PrivateKey.generate()
        node_private_bytes = node_private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        node_public_bytes = node_private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        node_id = ed25519_public_key_to_peer_id(node_public_bytes)

        # miner's key-pair uses ECDSA over secp256k1, cause it's used in
        # BTTC chain, a Ethereum compatible chain.
        # miner's nodes can share one wallet address
        wallet_private_key = ec.generate_private_key(ec.SECP256K1())
        wallet_private_value = wallet_private_key.private_numbers().private_value.to_bytes(
            32, "big"
        )
        wallet_public_bytes = wallet_private_key.public_key().public_bytes(
            encoding=serialization.Encoding.X962,
            format=serialization.PublicFormat.UncompressedPoint,
        )
        # Ethereum-like wallet address
        wallet_address = "0x" + keccak(wallet_public_bytes[1:])[-20:].hex()

        return Identity(
            node_id=node_id,
            node_key_type="ed25519",
            node_public_key=node_public_bytes.hex(),
            node_private_key=node_private_bytes.hex(),
            wallet_key_type="secp256k1",
            wallet_public_key=wallet_public_bytes.hex(),
            wallet_private_key=wallet_private_value.hex(),
            wallet_address=wallet_address,
            created_at=int(time.time()),
        )
