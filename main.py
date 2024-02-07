#!/usr/bin/env python3
import asyncio
import logging
import os
import sys
import time
from random import randint
from types import TracebackType
from typing import Awaitable, Callable, Concatenate, Optional, ParamSpec, Type, TypeVar

import aiohttp
import pandas as pd
import uvloop
from aiohttp.client import _RequestContextManager

RPC_URL = os.environ["RPC_URL"]

P = ParamSpec("P")
T = TypeVar("T")

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


# NOTE: could do a decorator but cba
async def safe_fetch(
    fetch_function: Callable[Concatenate[aiohttp.ClientSession, P], Awaitable[T]],
    session: aiohttp.ClientSession,
    *args: P.args,
    **kwargs: P.kwargs,
) -> tuple[T | None, None | Exception]:
    try:
        return await fetch_function(session, *args, **kwargs), None
    except Exception as e:
        return None, e


async def do_post(session, payload) -> bytes:
    async with session.post(RPC_URL, json=payload) as resp:
        return await resp.read()


async def fetch_storage_at(
    session: aiohttp.ClientSession,
    contract_address: str,
    positions: list[str],
    batch: bool = False,
):
    if batch:
        tasks = []
        # Split positions into chunks of 1000 for batching
        for i in range(0, len(positions), 1000):
            chunk = positions[i : i + 1000]
            payload = [
                {
                    "method": "eth_getStorageAt",
                    "params": [contract_address, pos, "latest"],
                    "id": n,
                    "jsonrpc": "2.0",
                }
                for n, pos in enumerate(chunk)
            ]
            tasks.append(do_post(session, payload))
        return await asyncio.gather(*tasks)
    else:
        # Handle individual requests in parallel
        return await asyncio.gather(
            *(
                do_post(
                    session,
                    {
                        "method": "eth_getStorageAt",
                        "params": [contract_address, position, "latest"],
                        "id": 1,
                        "jsonrpc": "2.0",
                    },
                )
                for position in positions
            )
        )


async def fetch_eth_call_with_state_override(
    session: aiohttp.ClientSession, contract_address: str, storage_positions: list[str]
):
    tasks = []
    # NOTE: can do larger batches but we'll be pessimistic
    for i in range(0, len(storage_positions), 15_000):
        batch = storage_positions[i : i + 15_000]

        # Construct calldata as a contiguous 32-byte array of all storage locations
        calldata = "0x" + "".join([pos[2:].rjust(64, "0") for pos in batch])

        # Specify the contract code to execute
        contract_code = "0x5f5b80361460135780355481526020016001565b365ff3"

        # Prepare the eth_call request with state override
        payload = {
            "method": "eth_call",
            "params": [
                {
                    "to": contract_address,
                    "data": calldata,
                },
                "latest",
                {contract_address: {"code": contract_code}},
            ],
            "id": 1,
            "jsonrpc": "2.0",
        }
        tasks.append(do_post(session, payload))
    return await asyncio.gather(*tasks)


async def benchmark(
    session: aiohttp.ClientSession,
    contract_address: str,
    storage_counts,
    latency_ms,
    conn_count,
) -> list[dict]:
    results = []
    for storage_count in storage_counts:
        # Generate random storage positions
        storage_positions = [
            hex(randint(0, 2**256 - 1)) for _ in range(storage_count)
        ]

        # Initialize record for this benchmark
        record = {
            "Latency (ms)": latency_ms,
            "Connections": conn_count,
            "Storage Lookups": storage_count,
        }

        method = "Individual"
        logging.info(f"{storage_count=} {conn_count=} {latency_ms=} {method=}")

        start_time = time.time()
        # Benchmark without batching
        _, error = await safe_fetch(
            fetch_storage_at, session, contract_address, storage_positions, batch=False
        )
        record["Method"] = method
        record["Duration (s)"] = None if error else time.time() - start_time
        results.append(record.copy())

        method = "Batching"
        logging.info(f"{storage_count=} {conn_count=} {latency_ms=} {method=}")

        # Benchmark with batching
        start_time = time.time()
        _, error = await safe_fetch(
            fetch_storage_at, session, contract_address, storage_positions, batch=True
        )
        record["Method"] = method
        record["Duration (s)"] = None if error else time.time() - start_time
        results.append(record.copy())

        method = "eth_call Override"
        logging.info(f"{storage_count=} {conn_count=} {latency_ms=} {method=}")
        # Benchmark eth_call with state override
        start_time = time.time()
        _, error = await safe_fetch(
            fetch_eth_call_with_state_override,
            session,
            contract_address,
            storage_positions,
        )
        record["Method"] = method
        record["Duration (s)"] = None if error else time.time() - start_time
        results.append(record.copy())

    return results


# Function to monkey patch aiohttp.ClientSession.post to simulate latency
def patch_aiohttp_with_latency(latency_ms):
    async def custom___aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        # Custom behavior here
        await asyncio.sleep(latency_ms / 1000)
        self._resp.release()
        await self._resp.wait_for_close()

    aiohttp.client._RequestContextManager.__aexit__ = custom___aexit__


async def main():
    contract_address = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
    storage_counts = [10, 100, 1000, 10000, 50000]
    latencies = [0, 20, 50, 100]  # No, low, medium, high latency in milliseconds
    connections = [1, 10, 50, 100, 200]
    all_results = []

    for conn_count in connections:
        logging.info(f"Connections: {conn_count}")
        for latency_ms in latencies:
            logging.info(f"Latency: {latency_ms}")
            async with aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(limit=conn_count),
                timeout=aiohttp.ClientTimeout(total=None),
            ) as session:
                patch_aiohttp_with_latency(latency_ms)
                results = await benchmark(
                    session, contract_address, storage_counts, latency_ms, conn_count
                )
                all_results.extend(results)

    df = pd.DataFrame(all_results)
    logging.info(df)
    df.to_csv("benchmark_results.csv", index=False)


if __name__ == "__main__":
    if sys.version_info >= (3, 11):
        with asyncio.Runner(loop_factory=uvloop.new_event_loop) as runner:
            runner.run(main())
    else:
        uvloop.install()
        asyncio.run(main())
