from __future__ import annotations

import asyncio
import logging
import socket
from dataclasses import dataclass

import psutil

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HostSnapshot:
    cpu_percent_x10: int
    memory_percent_x10: int

    def to_dict(self) -> dict[str, int]:
        return {
            "cpu_percent_x10": self.cpu_percent_x10,
            "memory_percent_x10": self.memory_percent_x10,
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
    return HostSnapshot(
        cpu_percent_x10=int(cpu_percent * 10 + 0.5),
        memory_percent_x10=int(memory_percent * 10 + 0.5),
    )


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
        logger.debug("nvidia-smi not found; gpu inventory unavailable")
        return []

    stdout, _stderr = await process.communicate()
    if process.returncode != 0:
        logger.debug(
            "nvidia-smi gpu inventory command failed: returncode=%s stderr=%s",
            process.returncode,
            _stderr.decode("utf-8", errors="replace")[:500],
        )
        return []
    items = _parse_nvidia_smi_csv(stdout.decode("utf-8"))

    if not items:
        logger.debug("nvidia-smi gpu inventory parsed no gpus")
    return items


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
