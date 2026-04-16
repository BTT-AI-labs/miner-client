from __future__ import annotations

import asyncio
import socket
from dataclasses import dataclass

import psutil


@dataclass(frozen=True)
class HostSnapshot:
    cpu_percent: float
    memory_percent: float

    def to_dict(self) -> dict[str, float]:
        return {
            "cpu_percent": self.cpu_percent,
            "memory_percent": self.memory_percent,
        }


@dataclass(frozen=True)
class GpuInventoryItem:
    index: int
    name: str | None
    vram_gb: float | None

    def to_dict(self) -> dict[str, int | float | str | None]:
        return {
            "index": self.index,
            "name": self.name,
            "vram_gb": self.vram_gb,
        }


def default_miner_name() -> str:
    return socket.gethostname().strip() or "miner-node"


async def collect_host_snapshot() -> HostSnapshot:
    cpu_percent, memory_percent = await asyncio.gather(
        asyncio.to_thread(psutil.cpu_percent, 0.1),
        asyncio.to_thread(lambda: float(psutil.virtual_memory().percent)),
    )
    return HostSnapshot(cpu_percent=float(cpu_percent), memory_percent=float(memory_percent))


async def collect_gpu_inventory() -> list[GpuInventoryItem]:
    try:
        process = await asyncio.create_subprocess_exec(
            "nvidia-smi",
            "--query-gpu=index,name,memory.total",
            "--format=csv,noheader,nounits",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        return []

    stdout, _stderr = await process.communicate()
    if process.returncode != 0:
        return []
    return _parse_nvidia_smi_csv(stdout.decode("utf-8"))


def _parse_nvidia_smi_csv(text: str) -> list[GpuInventoryItem]:
    items: list[GpuInventoryItem] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split(",", 2)]
        if len(parts) != 3:
            continue
        try:
            index = int(parts[0])
        except ValueError:
            continue
        try:
            vram_mb = float(parts[2])
        except ValueError:
            vram_mb = None
        items.append(
            GpuInventoryItem(
                index=index,
                name=parts[1] or None,
                vram_gb=round(vram_mb / 1024, 2) if vram_mb is not None else None,
            )
        )
    return items
