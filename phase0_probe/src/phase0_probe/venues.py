"""Public READ-ONLY endpoints + doc-sourced constants. No order-entry, signature or key-handling code exists in this package.

Sources (fetched 2026-11-26/27, snapshots in docs_snapshot/):
* Arcus REST base ``https://api.arcus.xyz`` (docs.arcus.xyz/api-reference/introduction.md),
  ``GET /v1/markets`` (api-reference/public/get-markets.md), ``GET /v1/markets/feeSchedules``
  (api-reference/public/get-market-fee-schedules.md), ``GET /v1/feetiers`` (api-reference/public/get-fee-tier-table.md).
* Arcus WS ``wss://api.arcus.xyz/v1/ws`` (api-reference/websocket.md); channels ``l2OrderbookUpdates``, ``l2Orderbook``,
  ``markets`` (api-reference/channels.md).
* Hyperliquid ``POST https://api.hyperliquid.xyz/info`` (for-developers/api/info-endpoint.md) with ``perpDexs``,
  ``metaAndAssetCtxs`` (+ ``dex``), ``predictedFundings`` (info-endpoint/perpetuals.md); WS ``wss://api.hyperliquid.xyz/ws``
  (for-developers/api/websocket.md) with ``l2``, ``l2Book``, ``activeAssetCtx`` (websocket/subscriptions.md).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

import aiohttp

from phase0_probe.dec import loads

ARCUS_REST = "https://api.arcus.xyz"
ARCUS_WS = "wss://api.arcus.xyz/v1/ws"
HL_INFO = "https://api.hyperliquid.xyz/info"
HL_WS = "wss://api.hyperliquid.xyz/ws"
ENTROPY_DEX = "io"                  # perpDexs: {"name": "io", "fullName": "EntropyIO"} (observed live)

# Hyperliquid perps fee tier 0 "Base rate" (hyperliquid-docs/trading/fees.md): taker 0.045 %, maker 0.015 %.
# The account's real tier needs ``userFees`` with an address — TODO: VERIFY_FROM_DOCS per account (Phase 1).
HL_BASE_TAKER = Decimal("0.00045")
HL_BASE_MAKER = Decimal("0.00015")
# Hyperliquid minimum order value: not stated on the fees / tick-and-lot-size / contract-spec pages.
# TODO: VERIFY_FROM_DOCS (the exchange rejects small orders; $10 is the commonly observed figure).
HL_MIN_NOTIONAL = Decimal(10)


async def get_json(session: aiohttp.ClientSession, url: str, *, params: dict[str, str] | None = None) -> Any:
    async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=20)) as r:
        r.raise_for_status()
        return loads(await r.read())


async def hl_info(session: aiohttp.ClientSession, body: dict[str, Any]) -> Any:
    async with session.post(HL_INFO, json=body, timeout=aiohttp.ClientTimeout(total=20)) as r:
        r.raise_for_status()
        return loads(await r.read())


def hip3_fee_scale(deployer_fee_scale: Decimal, growth_mode: bool) -> Decimal:
    """Multiplier on the user's base perp fee for a HIP-3 asset (hyperliquid-docs/trading/fees.md ``feeRates``):
    ``scaleIfHip3 = s + 1 if s < 1 else 2 s``; growth mode ×0.1. Referral / staking / aligned-quote discounts are
    ignored (worst case). TODO: VERIFY_FROM_DOCS whether ``isAlignedQuoteToken`` applies to dex 'io' collateral."""
    s = deployer_fee_scale
    scale = s + 1 if s < 1 else 2 * s
    return scale * (Decimal("0.1") if growth_mode else Decimal(1))
