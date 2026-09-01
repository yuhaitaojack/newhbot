from __future__ import annotations

import json
import logging
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.controllers.position_guard import GuardInput, PositionGuard
from app.core.enums import (
    CONFIRMED_LIVE_STATUSES,
    UNRESOLVED_ORDER_STATUSES,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSide,
    SignalType,
    SystemState,
)
from app.core.ids import new_cloid, new_id
from app.core.logging import log_extra
from app.events.hub import EventHub
from app.execution.protocol import ExecutionClient, PlaceOrderRequest
from app.models import Fill, Order, Signal, Trade
from app.recovery.manager import RecoveryManager
from app.repositories import (
    AuditRepository,
    EventRepository,
    FillRepository,
    OrderRepository,
    PositionRepository,
    ReservationRepository,
    SettingsRepository,
    SignalRepository,
    SnapshotRepository,
    TradeRepository,
)

logger = logging.getLogger(__name__)


class TradingController:
    """Sole business module allowed to request order execution."""

    def __init__(
        self,
        execution: ExecutionClient,
        recovery: RecoveryManager,
        hub: EventHub,
        guard: PositionGuard | None = None,
    ) -> None:
        self._execution = execution
        self._recovery = recovery
        self._hub = hub
        self._guard = guard or PositionGuard()

    async def handle_signal(self, session: AsyncSession, signal: SignalType, *, actor: str = "strategy") -> dict:
        settings = await SettingsRepository(session).get()
        record = Signal(
            id=new_id(),
            strategy_version=settings.active_strategy_version,
            signal=signal.value,
            accepted=False,
            reason=None,
        )
        await SignalRepository(session).add(record)
        await session.commit()

        if signal == SignalType.HOLD:
            record.accepted = True
            record.reason = "hold"
            await session.commit()
            await self._emit(session, "signal", {"signal": signal.value, "accepted": True})
            return {"accepted": True, "reason": "hold", "signal_id": record.id}

        local = await self._local_side(session, settings.trading_pair)
        if signal in {SignalType.LONG, SignalType.SHORT} and self._guard.reverse_is_forbidden(local, signal):
            record.reason = "automatic reverse is forbidden"
            await session.commit()
            await AuditRepository(session).add(
                "ignored_reverse",
                json.dumps({"signal": signal.value, "local": local.value}),
                actor=actor,
            )
            await session.commit()
            return {"accepted": False, "reason": record.reason, "signal_id": record.id}

        if signal in {SignalType.LONG, SignalType.SHORT}:
            result = await self._open(session, signal, record)
            return result
        return await self._close_position(session, record, stop_after=False)

    async def reconcile_after_restart(self, session: AsyncSession) -> dict:
        """Crash recovery. Query-only. Never calls place_order."""
        orders = await OrderRepository(session).list_unresolved()
        for order in orders:
            if str(order.status) == OrderStatus.SUBMITTING.value:
                order.status = OrderStatus.UNKNOWN.value
                prior = order.error_message or ""
                order.error_message = (prior + "; " if prior else "") + "crash while SUBMITTING; will not resubmit"
                await session.commit()
                logger.error(
                    "SUBMITTING promoted to UNKNOWN on restart; will not resubmit",
                    extra=log_extra(
                        request_id=order.request_id,
                        order_id=order.id,
                        cloid=order.cloid,
                        symbol=order.symbol,
                        side=order.side,
                    ),
                )
            await self._reconcile_unknown(session, order)
        remaining = await OrderRepository(session).has_unresolved()
        reserved = await ReservationRepository(session).current_order_id()
        return {
            "reconciled": len(orders),
            "still_unresolved": remaining,
            "reservation_held": reserved is not None,
        }

    async def start(self, session: AsyncSession) -> dict:
        settings = await SettingsRepository(session).get()
        if settings.estop:
            return {"ok": False, "reason": "emergency stop is latched; clear estop before start"}
        await self.reconcile_after_restart(session)
        if await OrderRepository(session).has_unresolved():
            await self._recovery.enter_recovery(session, "unresolved_orders")
            return {"ok": False, "reason": "unresolved orders present; new opens forbidden"}
        settings.trading_enabled = True
        await self._recovery.set_state(session, SystemState.STARTING, "user_start")
        connected = await self._execution.health()
        if not connected:
            await self._recovery.set_state(session, SystemState.CONNECTING, "worker_down")
            return {"ok": False, "reason": "execution worker unreachable"}
        await self._execution.connect()
        await self._recovery.set_state(session, SystemState.SYNCING, "user_start")
        await self._sync_exchange_mirror(session, settings.trading_pair)
        if await OrderRepository(session).has_unresolved():
            await self._recovery.enter_recovery(session, "unresolved_orders")
            return {"ok": False, "reason": "unresolved orders present; new opens forbidden"}
        await self._recovery.set_state(session, SystemState.RUNNING, "user_start")
        await AuditRepository(session).add("start", "{}", actor="user")
        await session.commit()
        await self._emit(
            session,
            "strategy_status",
            {
                "active_strategy": settings.active_strategy,
                "active_strategy_version": settings.active_strategy_version,
                "trading_enabled": True,
            },
        )
        return {"ok": True, "state": SystemState.RUNNING.value}

    async def stop(self, session: AsyncSession) -> dict:
        settings = await SettingsRepository(session).get()
        settings.trading_enabled = False
        await self._cancel_opening_orders(session)
        await self._recovery.set_state(session, SystemState.STOPPED, "user_stop")
        await AuditRepository(session).add("stop", "{}", actor="user")
        await session.commit()
        return {"ok": True, "state": SystemState.STOPPED.value}

    async def close_and_stop(self, session: AsyncSession) -> dict:
        await AuditRepository(session).add("close_and_stop", "{}", actor="user")
        close_result = await self._close_position(session, None, stop_after=True)
        return close_result

    async def close_and_continue(self, session: AsyncSession) -> dict:
        await AuditRepository(session).add("close_and_continue", "{}", actor="user")
        return await self._close_position(session, None, stop_after=False)

    async def emergency_stop(self, session: AsyncSession) -> dict:
        settings = await SettingsRepository(session).get()
        settings.estop = True
        settings.trading_enabled = False
        await self._cancel_all_orders(session)
        close_result = await self._close_position(session, None, stop_after=True, emergency=True)
        await AuditRepository(session).add("emergency_stop", json.dumps(close_result), actor="user")
        await session.commit()
        return close_result

    async def _open(self, session: AsyncSession, signal: SignalType, record: Signal) -> dict:
        settings = await SettingsRepository(session).get()
        connected = await self._execution.health()
        exchange_side = PositionSide.UNKNOWN
        foreign = False
        if connected:
            try:
                exchange_side = (await self._execution.get_position(settings.trading_pair)).side
                positions = await self._execution.get_positions()
                foreign = any(
                    item.side != PositionSide.FLAT and item.symbol != settings.trading_pair for item in positions
                )
            except Exception:
                connected = False
        local = await self._local_side(session, settings.trading_pair)
        has_unresolved = await OrderRepository(session).has_unresolved()
        reservation_held = await ReservationRepository(session).current_order_id() is not None
        guard = self._guard.can_open_position(
            GuardInput(
                local_side=local,
                exchange_side=exchange_side,
                has_unknown_orders=has_unresolved,
                system_state=SystemState(settings.system_state),
                configured_pair=settings.trading_pair,
                target_pair=settings.trading_pair,
                exchange_connected=connected,
                has_foreign_positions=foreign,
                has_open_reservation=reservation_held,
            )
        )
        if not guard.allowed:
            record.reason = guard.reason
            await session.commit()
            logger.warning("open rejected: %s", guard.reason, extra=log_extra(signal_id=record.id, symbol=settings.trading_pair))
            return {"accepted": False, "reason": guard.reason, "signal_id": record.id}

        side = OrderSide.BUY if signal == SignalType.LONG else OrderSide.SELL
        quantity = await self._size_from_settings(session)
        order_id = new_id()
        reserved = await ReservationRepository(session).try_acquire(order_id, reason="open")
        if not reserved:
            record.reason = "open reservation held; concurrent or in-flight open exists"
            await session.commit()
            return {"accepted": False, "reason": record.reason, "signal_id": record.id}

        order = await self._submit(
            session,
            symbol=settings.trading_pair,
            side=side,
            quantity=quantity,
            reduce_only=False,
            signal_id=record.id,
            order_id=order_id,
        )
        record.accepted = str(order.status) in {item.value for item in CONFIRMED_LIVE_STATUSES}
        record.reason = str(order.status)
        await session.commit()
        return {
            "accepted": record.accepted,
            "reason": record.reason,
            "signal_id": record.id,
            "cloid": order.cloid,
            "status": str(order.status),
        }

    async def _close_position(
        self,
        session: AsyncSession,
        record: Signal | None,
        *,
        stop_after: bool,
        emergency: bool = False,
    ) -> dict:
        settings = await SettingsRepository(session).get()
        settings.close_intent = "in_progress"
        await session.commit()
        try:
            exchange = await self._execution.get_position(settings.trading_pair)
        except Exception as exc:
            await self._recovery.enter_recovery(session, f"close_query_failed:{exc}")
            if record:
                record.reason = "exchange query failed"
                await session.commit()
            return {"ok": False, "reason": "exchange query failed"}

        if exchange.side == PositionSide.FLAT:
            settings.close_intent = None
            await ReservationRepository(session).release()
            if stop_after:
                settings.trading_enabled = False
                await self._recovery.set_state(session, SystemState.STOPPED, "close_already_flat")
            if record:
                record.accepted = True
                record.reason = "already_flat"
            await session.commit()
            return {"ok": True, "reason": "already_flat"}

        await self._cancel_opening_orders(session)
        close_side = OrderSide.SELL if exchange.side == PositionSide.LONG else OrderSide.BUY
        order = await self._submit(
            session,
            symbol=settings.trading_pair,
            side=close_side,
            quantity=exchange.size,
            reduce_only=True,
            signal_id=record.id if record else None,
        )
        if order.status == OrderStatus.UNKNOWN:
            await self._recovery.enter_recovery(session, "unknown_close")
            return {"ok": False, "reason": "close order UNKNOWN", "cloid": order.cloid}

        await self._sync_exchange_mirror(session, settings.trading_pair)
        settings.close_intent = None
        live = await self._execution.get_position(settings.trading_pair)
        if live.side == PositionSide.FLAT:
            await ReservationRepository(session).release()
        if stop_after:
            settings.trading_enabled = False
            state = SystemState.STOPPED if not emergency else SystemState.STOPPED
            await self._recovery.set_state(session, state, "close_and_stop" if not emergency else "emergency_stop")
        if record:
            record.accepted = True
            record.reason = "closed"
        await session.commit()
        return {"ok": True, "cloid": order.cloid, "status": str(order.status)}

    async def _submit(
        self,
        session: AsyncSession,
        *,
        symbol: str,
        side: OrderSide,
        quantity: Decimal,
        reduce_only: bool,
        signal_id: str | None,
        order_id: str | None = None,
    ) -> Order:
        settings = await SettingsRepository(session).get()
        request_id = new_id()
        intent_id = new_id()
        cloid = new_cloid()
        order = Order(
            id=order_id or new_id(),
            intent_id=intent_id,
            request_id=request_id,
            cloid=cloid,
            symbol=symbol,
            side=side.value,
            order_type=settings.order_type,
            quantity=quantity,
            reduce_only=reduce_only,
            status=OrderStatus.PENDING_SUBMISSION.value,
            signal_id=signal_id,
        )
        await OrderRepository(session).add(order)
        await session.commit()
        logger.info(
            "order intent persisted as PENDING_SUBMISSION",
            extra=log_extra(request_id=request_id, order_id=order.id, cloid=cloid, symbol=symbol, side=side.value),
        )

        order.status = OrderStatus.SUBMITTING.value
        await session.commit()
        logger.info(
            "order SUBMITTING; calling execution worker once",
            extra=log_extra(request_id=request_id, order_id=order.id, cloid=cloid, symbol=symbol, side=side.value),
        )

        request = PlaceOrderRequest(
            request_id=request_id,
            cloid=cloid,
            symbol=symbol,
            side=side,
            order_type=OrderType(settings.order_type),
            quantity=quantity,
            reduce_only=reduce_only,
        )
        try:
            response = await self._execution.place_order(request)
        except Exception as exc:
            logger.warning(
                "place_order raised; marking UNKNOWN and querying; will not resubmit",
                extra=log_extra(request_id=request_id, cloid=cloid, symbol=symbol, side=side.value),
            )
            order.status = OrderStatus.UNKNOWN.value
            order.error_message = str(exc)
            await session.commit()
            await self._reconcile_unknown(session, order)
            return order

        order.exchange_oid = response.exchange_oid
        order.status = response.status.value
        order.error_message = response.error
        await session.commit()
        if response.status in {OrderStatus.FILLED, OrderStatus.PARTIAL} and response.filled_quantity > 0:
            await self._record_fill(session, order, response.avg_price or Decimal("0"), response.filled_quantity)
        if str(order.status) == OrderStatus.REJECTED.value and not reduce_only:
            await ReservationRepository(session).release(order.id)
        await self._sync_exchange_mirror(session, symbol)
        await self._emit(session, "order", {"cloid": cloid, "status": order.status})
        return order

    async def _reconcile_unknown(self, session: AsyncSession, order: Order) -> None:
        """Query-only. Never calls place_order. Absence of an open order is not enough."""
        order_ok = True
        viewed = None
        try:
            viewed = await self._execution.get_order(order.cloid)
        except Exception as exc:
            order_ok = False
            order.error_message = f"get_order failed: {exc}"

        fills_ok = True
        matching_fills = []
        try:
            fills = await self._execution.get_fills()
            matching_fills = [item for item in fills if item.cloid == order.cloid]
        except Exception as exc:
            fills_ok = False
            order.error_message = f"get_fills failed: {exc}"

        position_ok = True
        position = None
        try:
            position = await self._execution.get_position(order.symbol)
        except Exception as exc:
            position_ok = False
            order.error_message = f"get_position failed: {exc}"

        if not (order_ok and fills_ok and position_ok):
            order.status = OrderStatus.UNKNOWN.value
            await self._recovery.enter_recovery(session, "unconfirmed_place")
            logger.error(
                "order remains UNKNOWN; order/fills/position not all queryable",
                extra=log_extra(request_id=order.request_id, cloid=order.cloid, order_id=order.id),
            )
            await session.commit()
            await self._emit(session, "order", {"cloid": order.cloid, "status": OrderStatus.UNKNOWN.value})
            return

        if viewed is not None:
            order.status = viewed.status.value
            order.exchange_oid = viewed.exchange_oid
            if matching_fills and str(order.status) in {OrderStatus.FILLED.value, OrderStatus.PARTIAL.value}:
                for fill in matching_fills:
                    await self._record_fill(session, order, fill.price, fill.quantity)
            await session.commit()
            await self._sync_exchange_mirror(session, order.symbol)
            await self._maybe_leave_recovery(session)
            await self._emit(session, "order", {"cloid": order.cloid, "status": order.status})
            return

        if matching_fills:
            order.status = OrderStatus.UNKNOWN.value
            order.error_message = "fills exist without get_order hit; cannot treat as unsubmitted"
            await self._recovery.enter_recovery(session, "fill_without_order")
            await session.commit()
            return

        if position is not None and not order.reduce_only and position.side != PositionSide.FLAT:
            order.status = OrderStatus.UNKNOWN.value
            order.error_message = "position is not FLAT without a matching order; cannot treat as unsubmitted"
            await self._recovery.enter_recovery(session, "position_without_order")
            await session.commit()
            return

        if order.reduce_only and position is not None and position.side != PositionSide.FLAT:
            order.status = OrderStatus.UNKNOWN.value
            order.error_message = "close unconfirmed: no order/fill and position still open"
            await self._recovery.enter_recovery(session, "unconfirmed_close")
            await session.commit()
            return

        order.status = OrderStatus.REJECTED.value
        order.error_message = "confirmed absent: no order, no fill, position compatible with unsubmitted"
        if not order.reduce_only:
            await ReservationRepository(session).release(order.id)
        await session.commit()
        await self._maybe_leave_recovery(session)
        logger.warning(
            "UNKNOWN cleared to REJECTED after order+fills+position confirmed absent",
            extra=log_extra(request_id=order.request_id, cloid=order.cloid, order_id=order.id),
        )
        await self._emit(session, "order", {"cloid": order.cloid, "status": order.status})

    async def _maybe_leave_recovery(self, session: AsyncSession) -> None:
        if await OrderRepository(session).has_unresolved():
            return
        settings = await SettingsRepository(session).get()
        if settings.system_state != SystemState.RECOVERY.value or settings.estop:
            return
        nxt = SystemState.RUNNING if settings.trading_enabled else SystemState.STOPPED
        await self._recovery.set_state(session, nxt, "unresolved_orders_cleared")

    async def _record_fill(self, session: AsyncSession, order: Order, price: Decimal, quantity: Decimal) -> None:
        fill = Fill(
            id=new_id(),
            order_id=order.id,
            cloid=order.cloid,
            symbol=order.symbol,
            side=order.side,
            price=price,
            quantity=quantity,
        )
        await FillRepository(session).add(fill)
        await session.commit()
        await self._emit(
            session,
            "fill",
            {"cloid": order.cloid, "price": str(price), "quantity": str(quantity)},
        )
        trades = TradeRepository(session)
        if order.reduce_only:
            open_trade = await trades.open_trade(order.symbol)
            if open_trade is not None:
                open_trade.exit_price = price
                open_trade.pnl = (price - open_trade.entry_price) * open_trade.quantity
                if open_trade.side == OrderSide.SELL.value:
                    open_trade.pnl = -open_trade.pnl
                from datetime import datetime, timezone

                open_trade.closed_at = datetime.now(timezone.utc)
                await session.commit()
                await self._emit(session, "trade", {"id": open_trade.id, "pnl": str(open_trade.pnl)})
        else:
            trade = Trade(
                id=new_id(),
                symbol=order.symbol,
                side=order.side,
                entry_price=price,
                quantity=quantity,
            )
            await trades.add(trade)
            await session.commit()

    async def _sync_exchange_mirror(self, session: AsyncSession, symbol: str) -> None:
        # Exchange State > Local DB
        try:
            view = await self._execution.get_position(symbol)
            balance = await self._execution.get_balance()
        except Exception:
            return
        await PositionRepository(session).upsert_mirror(
            symbol, view.side, view.size, view.entry_price, view.unrealized_pnl
        )
        await SnapshotRepository(session).add(balance.equity, balance.available, balance.margin_used)
        await session.commit()
        await self._emit(
            session,
            "position",
            {"symbol": symbol, "side": view.side.value, "size": str(view.size)},
        )

    async def _local_side(self, session: AsyncSession, symbol: str) -> PositionSide:
        row = await PositionRepository(session).get(symbol)
        return PositionSide(row.side)

    async def _size_from_settings(self, session: AsyncSession) -> Decimal:
        settings = await SettingsRepository(session).get()
        try:
            market = await self._execution.get_market_data(settings.trading_pair)
            mid = market.get("mid", Decimal("100"))
            balance = await self._execution.get_balance()
            notional = balance.equity * (settings.position_percentage / Decimal("100"))
            qty = notional / mid if mid else Decimal("0.001")
            return qty.quantize(Decimal("0.0001"))
        except Exception:
            return Decimal("0.001")

    async def _cancel_opening_orders(self, session: AsyncSession) -> None:
        for order in await OrderRepository(session).list_open():
            if order.reduce_only:
                continue
            request_id = new_id()
            try:
                viewed = await self._execution.cancel_order(order.cloid, request_id)
            except Exception:
                order.status = OrderStatus.UNKNOWN.value
                continue
            if viewed:
                order.status = viewed.status.value
        await session.commit()

    async def _cancel_all_orders(self, session: AsyncSession) -> None:
        for order in await OrderRepository(session).list_open():
            request_id = new_id()
            try:
                viewed = await self._execution.cancel_order(order.cloid, request_id)
            except Exception:
                order.status = OrderStatus.UNKNOWN.value
                continue
            if viewed:
                order.status = viewed.status.value
        await session.commit()

    async def _emit(self, session: AsyncSession, event_type: str, payload: dict) -> None:
        event = await EventRepository(session).add(event_type, json.dumps(payload, default=str))
        await session.commit()
        await self._hub.publish(event_type, payload, event.id)
