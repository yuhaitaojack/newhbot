from __future__ import annotations

from app.exchange_models import ExchangeFill, ExchangeOrder, ExchangePosition, SyncStatus
from app.protocol import OrderStatus, PositionSide


class ExchangeStateStore:
    """TEST HELPER ONLY. Not used on the production Adapter path.

    STEP 2 execution-layer truth is the Connector (account_positions /
    in_flight_orders / fills). Do not reintroduce this store as a second
    exchange state source.
    """

    def __init__(self) -> None:
        self.positions: dict[str, ExchangePosition] = {}
        self.orders: dict[str, ExchangeOrder] = {}
        self.fills: list[ExchangeFill] = []
        self._fill_ids: set[str] = set()
        self.sync_status = SyncStatus.NONE
        self.ws_connected = False
        self.needs_reconciliation = False
        self.conflict_reason: str | None = None

    def apply_rest_snapshot(
        self,
        *,
        positions: list[ExchangePosition],
        orders: list[ExchangeOrder],
        fills: list[ExchangeFill] | None = None,
    ) -> None:
        self.positions = {item.symbol: item for item in positions if item.side != PositionSide.FLAT}
        self.orders = {item.cloid: item for item in orders}
        if fills is not None:
            self.fills = []
            self._fill_ids = set()
            for item in fills:
                self._remember_fill(item)
        self.sync_status = SyncStatus.SNAPSHOT
        self.needs_reconciliation = False
        self.conflict_reason = None

    def apply_ws_order(self, order: ExchangeOrder) -> None:
        existing = self.orders.get(order.cloid)
        self.orders[order.cloid] = order
        if order.status in {OrderStatus.CANCELED, OrderStatus.REJECTED, OrderStatus.FILLED}:
            if order.status != OrderStatus.FILLED or order.remaining_quantity <= 0:
                if order.status in {OrderStatus.CANCELED, OrderStatus.REJECTED}:
                    self.orders.pop(order.cloid, None)
        if existing and existing.status == OrderStatus.FILLED and order.status == OrderStatus.OPEN:
            self.needs_reconciliation = True
            self.conflict_reason = "ws OPEN after REST/WS FILLED"
            self.sync_status = SyncStatus.CONFLICT
            return
        if self.ws_connected:
            self.sync_status = SyncStatus.LIVE

    def apply_ws_fill(self, fill: ExchangeFill, position: ExchangePosition | None = None) -> None:
        if not self._remember_fill(fill):
            return
        if fill.cloid in self.orders:
            order = self.orders[fill.cloid]
            filled = order.filled_quantity + fill.quantity
            remaining = order.quantity - filled
            status = OrderStatus.FILLED if remaining <= 0 else OrderStatus.PARTIAL
            self.orders[fill.cloid] = order.model_copy(
                update={"filled_quantity": filled, "remaining_quantity": max(remaining, 0), "status": status}
            )
        if position is not None:
            if position.side == PositionSide.FLAT or position.size == 0:
                self.positions.pop(position.symbol, None)
            else:
                self.positions[position.symbol] = position
        if self.ws_connected:
            self.sync_status = SyncStatus.LIVE

    def apply_ws_position(self, position: ExchangePosition) -> None:
        rest = self.positions.get(position.symbol)
        if rest is not None and rest.side != PositionSide.FLAT and position.side != PositionSide.FLAT and rest.side != position.side:
            self.needs_reconciliation = True
            self.conflict_reason = f"REST {rest.side} vs WS {position.side} on {position.symbol}"
            self.sync_status = SyncStatus.CONFLICT
            # Exchange WS is newer incremental truth only after explicit resync; do not silently overwrite.
            return
        if position.side == PositionSide.FLAT or position.size == 0:
            self.positions.pop(position.symbol, None)
        else:
            self.positions[position.symbol] = position
        if self.ws_connected and not self.needs_reconciliation:
            self.sync_status = SyncStatus.LIVE

    def _remember_fill(self, fill: ExchangeFill) -> bool:
        if fill.fill_id and fill.fill_id in self._fill_ids:
            return False
        if fill.fill_id:
            self._fill_ids.add(fill.fill_id)
        self.fills.append(fill)
        return True

    def mark_conflict(self, reason: str) -> None:
        self.needs_reconciliation = True
        self.conflict_reason = reason
        self.sync_status = SyncStatus.CONFLICT

    def mark_ws(self, connected: bool) -> None:
        self.ws_connected = connected
        if not connected:
            self.sync_status = SyncStatus.RESYNC

    def resync_from_rest(
        self,
        *,
        positions: list[ExchangePosition],
        orders: list[ExchangeOrder],
        fills: list[ExchangeFill] | None = None,
    ) -> None:
        """Apply a REST snapshot after WS drop or CONFLICT, then re-verify before READY."""
        self.apply_rest_snapshot(positions=positions, orders=orders, fills=fills)
        self.sync_status = SyncStatus.SNAPSHOT
