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

        if signal == SignalType.CLOSE and settings.system_state == SystemState.RECOVERY.value:
            record.reason = "recovery forbids strategy close; explicit close required"
            await session.commit()
            await AuditRepository(session).add(
                "ignored_strategy_close_in_recovery",
                json.dumps({"signal": signal.value}),
                actor=actor,
            )
            await session.commit()
            return {"accepted": False, "reason": record.reason, "signal_id": record.id}

        if settings.close_intent == "in_progress":
            record.reason = "close in progress"
            await session.commit()
            await AuditRepository(session).add(
                "ignored_during_close",
                json.dumps({"signal": signal.value}),
                actor=actor,
            )
            await session.commit()
            return {"accepted": False, "reason": record.reason, "signal_id": record.id}

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
        await self._recovery.set_state(session, SystemState.STARTING, "user_start")
        try:
            connected = await self._execution.health()
        except Exception as exc:
            await self._recovery.enter_recovery(session, f"worker_health_query_failed:{type(exc).__name__}")
            return {"ok": False, "reason": "execution worker health query failed; recovery required"}
        if not connected:
            await self._recovery.enter_recovery(session, "worker_unreachable")
            return {"ok": False, "reason": "execution worker unreachable; recovery required"}
        try:
            await self._execution.connect()
            configure = getattr(self._execution, "configure", None)
            if configure is not None:
                await configure(settings.trading_pair, settings.slippage, settings.leverage)
            ready = await self._execution.is_ready()
        except Exception as exc:
            await self._recovery.enter_recovery(session, f"worker_start_failed:{type(exc).__name__}")
            return {"ok": False, "reason": "execution worker startup failed; recovery required"}
        if not ready:
            await self._recovery.enter_recovery(session, "worker_not_ready")
            return {"ok": False, "reason": "execution worker not READY"}
        await self._recovery.set_state(session, SystemState.SYNCING, "user_start")
        synced = await self._sync_exchange_mirror(session, settings.trading_pair)
        mirror = await PositionRepository(session).get_or_none(settings.trading_pair)
        if (
            not synced
            or mirror is None
            or mirror.side == PositionSide.UNKNOWN.value
        ):
            await self._recovery.enter_recovery(session, "exchange_mirror_unavailable")
            return {"ok": False, "reason": "exchange position query failed"}
        try:
            positions = await self._execution.get_positions()
        except Exception as exc:
            await self._recovery.enter_recovery(session, f"exchange_positions_query_failed:{type(exc).__name__}")
            return {"ok": False, "reason": "exchange positions query failed"}
        if any(item.side != PositionSide.FLAT and item.symbol != settings.trading_pair for item in positions):
            await self._recovery.enter_recovery(session, "foreign_position_present")
            return {"ok": False, "reason": "foreign exchange position present; recovery required"}
        try:
            open_orders = await self._execution.get_open_orders()
        except Exception as exc:
            await self._recovery.enter_recovery(session, f"exchange_open_orders_query_failed:{type(exc).__name__}")
            return {"ok": False, "reason": "exchange open orders query failed"}
        if open_orders:
            await self._recovery.enter_recovery(session, "exchange_open_orders_present")
            return {"ok": False, "reason": "exchange open orders present; recovery required"}
        if mirror.side == PositionSide.FLAT.value:
            await self._terminalize_stale_openings_after_flat(session, settings.trading_pair)
        if await OrderRepository(session).has_unresolved():
            await self._recovery.enter_recovery(session, "unresolved_orders")
            return {"ok": False, "reason": "unresolved orders present; new opens forbidden"}
        # Do not persist the trading switch until every worker and exchange
        # preflight has succeeded. Failed starts must remain disabled in
        # RECOVERY instead of leaving a misleading enabled flag behind.
        settings.trading_enabled = True
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

    async def _terminalize_stale_openings_after_flat(self, session: AsyncSession, symbol: str) -> int:
        """Close local ACK/OPEN/PARTIAL opening rows only after exchange FLAT + no open orders.

        Exchange state is authoritative. This repairs a local lifecycle gap where a filled
        market entry was left OPEN after its exchange order disappeared, without deleting
        the audit row or permitting a new order while an exchange order is still live.
        """
        stale = await OrderRepository(session).list_reconcilable_opening(symbol)
        for order in stale:
            order.status = OrderStatus.CANCELED.value
            prior = order.error_message or ""
            order.error_message = (
                f"{prior}; " if prior else ""
            ) + "terminalized during exchange-flat reconciliation; no exchange open order"
            await AuditRepository(session).add(
                "stale_opening_terminalized",
                json.dumps({"order_id": order.id, "cloid": order.cloid, "symbol": symbol}),
                actor="recovery",
            )
        if stale:
            await session.commit()
        return len(stale)

    async def enter_recovery(self, session: AsyncSession, reason: str) -> None:
        """Move the persisted control state to Recovery after a supervised failure."""
        await self._recovery.enter_recovery(session, reason)

    async def stop(self, session: AsyncSession) -> dict:
        settings = await SettingsRepository(session).get()
        settings.trading_enabled = False
        canceled = await self._cancel_opening_orders(session)
        if not canceled:
            await self._recovery.enter_recovery(session, "stop_cancel_unconfirmed")
            await session.commit()
            return {"ok": False, "reason": "open order cancellation unconfirmed; recovery required"}
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
        canceled = await self._cancel_all_orders(session)
        if not canceled:
            await self._recovery.enter_recovery(session, "emergency_cancel_unconfirmed")
            close_result = {
                "ok": False,
                "reason": "order cancellation unconfirmed; recovery required",
            }
        else:
            close_result = await self._close_position(session, None, stop_after=True, emergency=True)
        await AuditRepository(session).add("emergency_stop", json.dumps(close_result), actor="user")
        await session.commit()
        return close_result

    async def clear_estop(self, session: AsyncSession) -> dict:
        """Query-only unlatch. Never places, cancels, sets leverage, or starts trading."""
        settings = await SettingsRepository(session).get()
        audit = AuditRepository(session)

        async def reject(reason: str, *, recovery: bool = False) -> dict:
            if recovery:
                await self._recovery.enter_recovery(session, f"clear_estop:{reason}")
            fresh = await SettingsRepository(session).get()
            await audit.add("clear_estop_rejected", json.dumps({"reason": reason}), actor="user")
            await session.commit()
            await self._emit(session, "estop", {"estop": True, "cleared": False, "reason": reason})
            return {
                "ok": False,
                "reason": reason,
                "estop": True,
                "state": fresh.system_state,
            }

        if not settings.estop:
            return await reject("emergency stop is not latched")
        if await OrderRepository(session).has_unresolved():
            return await reject("unresolved or UNKNOWN orders present")
        if await OrderRepository(session).list_open():
            return await reject("open orders present")

        try:
            connected = await self._execution.health()
        except Exception as exc:
            return await reject(f"worker health query failed: {type(exc).__name__}", recovery=True)
        if not connected:
            return await reject("execution worker unreachable", recovery=True)
        try:
            position = await self._execution.get_position(settings.trading_pair)
            positions = await self._execution.get_positions()
            open_orders = await self._execution.get_open_orders()
        except Exception as exc:
            return await reject(f"exchange query failed: {type(exc).__name__}", recovery=True)

        if position.side == PositionSide.UNKNOWN:
            return await reject("position side is UNKNOWN", recovery=True)
        if position.side != PositionSide.FLAT:
            return await reject("position is not FLAT")
        if any(item.side != PositionSide.FLAT and item.symbol != settings.trading_pair for item in positions):
            return await reject("foreign position present")
        if open_orders:
            return await reject("open orders present")

        settings.estop = False
        settings.trading_enabled = False
        if settings.system_state not in {SystemState.STOPPED.value, SystemState.RECOVERY.value}:
            await self._recovery.set_state(session, SystemState.STOPPED, "clear_estop")
        await audit.add(
            "clear_estop",
            json.dumps({"state": settings.system_state, "trading_enabled": False}),
            actor="user",
        )
        await session.commit()
        await self._emit(
            session,
            "estop",
            {
                "estop": False,
                "cleared": True,
                "trading_enabled": False,
                "state": settings.system_state,
            },
        )
        return {
            "ok": True,
            "estop": False,
            "state": settings.system_state,
            "reason": "estop_cleared_still_stopped",
        }

    async def _open(self, session: AsyncSession, signal: SignalType, record: Signal) -> dict:
        settings = await SettingsRepository(session).get()
        try:
            reachable = await self._execution.health()
            ready = await self._execution.is_ready() if reachable else False
        except Exception as exc:
            await self._recovery.enter_recovery(session, f"worker_status_query_failed:{type(exc).__name__}")
            record.reason = "execution worker status query failed; recovery required"
            await session.commit()
            return {"accepted": False, "reason": record.reason, "signal_id": record.id}
        exchange_side = PositionSide.UNKNOWN
        foreign = False
        if reachable:
            try:
                exchange_side = (await self._execution.get_position(settings.trading_pair)).side
                positions = await self._execution.get_positions()
                foreign = any(
                    item.side != PositionSide.FLAT and item.symbol != settings.trading_pair for item in positions
                )
                open_orders = await self._execution.get_open_orders()
                if open_orders:
                    await self._recovery.enter_recovery(session, "exchange_open_orders_present")
                    record.reason = "exchange open orders present"
                    await session.commit()
                    return {"accepted": False, "reason": record.reason, "signal_id": record.id}
                synced = await self._sync_exchange_mirror(session, settings.trading_pair)
                if not synced:
                    await self._recovery.enter_recovery(session, "exchange_mirror_unavailable")
                    record.reason = "exchange position query failed"
                    await session.commit()
                    return {"accepted": False, "reason": record.reason, "signal_id": record.id}
            except Exception as exc:
                ready = False
                reason = f"open_exchange_query_failed:{type(exc).__name__}"
                await self._recovery.enter_recovery(session, reason)
                record.reason = "exchange query failed"
                await session.commit()
                return {"accepted": False, "reason": record.reason, "signal_id": record.id}
        if not reachable:
            await self._recovery.enter_recovery(session, "worker_unreachable_during_open")
            record.reason = "execution worker unreachable; recovery required"
            await session.commit()
            return {"accepted": False, "reason": record.reason, "signal_id": record.id}
        if not ready:
            await self._recovery.enter_recovery(session, "worker_not_ready_during_open")
            record.reason = "execution worker not READY; recovery required"
            await session.commit()
            return {"accepted": False, "reason": record.reason, "signal_id": record.id}
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
                exchange_connected=ready,
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
        try:
            quantity = await self._size_from_settings(session)
        except Exception as exc:
            await self._recovery.enter_recovery(session, f"open_size_query_failed:{type(exc).__name__}")
            record.reason = f"size unavailable: {type(exc).__name__}"
            await session.commit()
            return {"accepted": False, "reason": record.reason, "signal_id": record.id}
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

        if exchange.side == PositionSide.UNKNOWN:
            await self._recovery.enter_recovery(session, "close_position_unknown")
            if record:
                record.reason = "exchange position unknown; recovery required"
                await session.commit()
            return {"ok": False, "reason": "exchange position unknown; recovery required"}

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

        canceled = await self._cancel_opening_orders(session)
        if not canceled:
            await self._recovery.enter_recovery(session, "close_cancel_unconfirmed")
            await session.commit()
            return {"ok": False, "reason": "open order cancellation unconfirmed; recovery required"}
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
        if order.status == OrderStatus.REJECTED:
            settings.close_intent = None
            await self._recovery.enter_recovery(
                session, f"close_rejected:{order.error_message or 'execution worker rejected order'}"
            )
            await session.commit()
            return {"ok": False, "reason": order.error_message or "close order rejected", "cloid": order.cloid}

        synced = await self._sync_exchange_mirror(session, settings.trading_pair)
        if not synced:
            await self._recovery.enter_recovery(session, "post_order_sync_failed")
            await session.commit()
            return {"ok": False, "reason": "close confirmation required", "cloid": order.cloid}
        try:
            live = await self._execution.get_position(settings.trading_pair)
        except Exception as exc:
            await self._recovery.enter_recovery(
                session, f"close_confirmation_query_failed:{type(exc).__name__}"
            )
            await session.commit()
            return {"ok": False, "reason": "close confirmation required", "cloid": order.cloid}
        if live.side == PositionSide.UNKNOWN:
            await self._recovery.enter_recovery(session, "close_confirmation_position_unknown")
            await session.commit()
            return {"ok": False, "reason": "close confirmation required", "cloid": order.cloid}
        if live.side != PositionSide.FLAT:
            await self._recovery.enter_recovery(
                session, f"close_confirmation_not_flat:{live.side.value}"
            )
            await session.commit()
            return {"ok": False, "reason": "close confirmation required", "cloid": order.cloid}
        await self._terminalize_stale_openings_after_flat(session, settings.trading_pair)
        settings.close_intent = None
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
        synced = await self._sync_exchange_mirror(session, symbol)
        if not synced:
            await self._recovery.enter_recovery(session, "post_order_sync_failed")
            await session.commit()
        elif order.order_type == OrderType.MARKET.value:
            if reduce_only:
                await self._finalize_confirmed_market_close(session, order)
            else:
                await self._finalize_confirmed_market_open(session, order)
        await self._emit(session, "order", {"cloid": cloid, "status": order.status})
        return order

    async def _finalize_confirmed_market_open(self, session: AsyncSession, order: Order) -> None:
        """Resolve an IOC response reported OPEN after exchange position confirms a full fill.

        Hyperliquid/Hummingbot can return the immediate IOC acknowledgement as
        OPEN before the fill event is reflected in the connector order object.
        Exchange position state is authoritative here, and the pre-open guard
        already proved this symbol was FLAT. Limit/GTC orders are intentionally
        excluded because an OPEN result may be a genuine resting order.
        """
        if order.order_type != OrderType.MARKET.value or order.status != OrderStatus.OPEN.value:
            return
        try:
            live = await self._execution.get_position(order.symbol)
            if live.side not in {PositionSide.LONG, PositionSide.SHORT} or live.size <= 0:
                return
            expected = PositionSide.LONG if order.side == OrderSide.BUY.value else PositionSide.SHORT
            if live.side != expected:
                return
            fills = await self._execution.get_fills()
            matching = [item for item in fills if item.cloid == order.cloid]
            filled_total = sum((item.quantity for item in matching), Decimal("0"))
            # Prefer exact fill evidence. If the connector has not propagated
            # the fill cloid yet, a nearly full exchange position is sufficient
            # evidence for an IOC; a clearly partial position remains OPEN.
            full = filled_total >= order.quantity * Decimal("0.99")
            if not matching:
                full = live.size >= order.quantity * Decimal("0.90")
            if not full:
                return
            order.status = OrderStatus.FILLED.value
            if matching:
                for fill in matching:
                    await self._record_fill(
                        session,
                        order,
                        fill.price,
                        fill.quantity,
                        fill_id=getattr(fill, "fill_id", None),
                    )
            else:
                # Position confirmation is the exchange truth when the fill
                # event has not arrived; preserve an auditable local fill.
                await self._record_fill(
                    session,
                    order,
                    live.entry_price or Decimal("0"),
                    live.size,
                )
            await session.commit()
        except Exception:
            # This is a confirmation enhancement, never permission to infer a
            # fill after a failed query. The original OPEN status remains and
            # the normal recovery/reconciliation path retains the safety gate.
            logger.exception("market open finalization query failed")

    async def _finalize_confirmed_market_close(self, session: AsyncSession, order: Order) -> None:
        """Resolve an IOC close reported OPEN after exchange position confirms FLAT.

        A reduce-only market close can receive the same immediate OPEN
        acknowledgement as an open.  Once the exchange position is FLAT, the
        close is complete and must not remain as a local open order that would
        poison the next pre-open guard.
        """
        if order.order_type != OrderType.MARKET.value or order.status != OrderStatus.OPEN.value:
            return
        try:
            live = await self._execution.get_position(order.symbol)
            if live.side != PositionSide.FLAT or live.size > 0:
                return
            fills = await self._execution.get_fills()
            matching = [item for item in fills if item.cloid == order.cloid]
            filled_total = sum((item.quantity for item in matching), Decimal("0"))
            if filled_total < order.quantity * Decimal("0.99"):
                return
            order.status = OrderStatus.FILLED.value
            for fill in matching:
                await self._record_fill(
                    session,
                    order,
                    fill.price,
                    fill.quantity,
                    fill_id=getattr(fill, "fill_id", None),
                )
            await session.commit()
        except Exception:
            # A failed confirmation query must retain the original OPEN state
            # and let normal reconciliation keep the safety gate closed.
            logger.exception("market close finalization query failed")

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
                    await self._record_fill(
                        session,
                        order,
                        fill.price,
                        fill.quantity,
                        fill_id=getattr(fill, "fill_id", None),
                    )
            await session.commit()
            synced = await self._sync_exchange_mirror(session, order.symbol)
            if not synced:
                await self._recovery.enter_recovery(session, "unknown_reconciliation_sync_failed")
                await session.commit()
                return
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

    async def _record_fill(
        self,
        session: AsyncSession,
        order: Order,
        price: Decimal,
        quantity: Decimal,
        *,
        fill_id: str | None = None,
    ) -> None:
        fill = Fill(
            id=new_id(),
            order_id=order.id,
            cloid=order.cloid,
            symbol=order.symbol,
            side=order.side,
            price=price,
            quantity=quantity,
            exchange_fill_id=fill_id,
        )
        stored, created = await FillRepository(session).add(fill)
        if not created:
            _ = stored
            return
        await session.commit()
        await self._emit(
            session,
            "fill",
            {"cloid": order.cloid, "price": str(price), "quantity": str(quantity), "fill_id": fill_id},
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

    async def _sync_exchange_mirror(self, session: AsyncSession, symbol: str) -> bool:
        # Exchange State > Local DB
        try:
            view = await self._execution.get_position(symbol)
            balance = await self._execution.get_balance()
        except Exception:
            return False
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
        return True

    async def _local_side(self, session: AsyncSession, symbol: str) -> PositionSide:
        row = await PositionRepository(session).get_or_none(symbol)
        if row is None:
            return PositionSide.UNKNOWN
        return PositionSide(row.side)

    async def _size_from_settings(self, session: AsyncSession) -> Decimal:
        settings = await SettingsRepository(session).get()
        market = await self._execution.get_market_data(settings.trading_pair)
        mid = Decimal(str(market.get("mid", "0")))
        if mid <= 0:
            raise ValueError("mid price unavailable")
        balance = await self._execution.get_balance()
        notional = balance.equity * (settings.position_percentage / Decimal("100"))
        if notional <= 0:
            raise ValueError("notional from settings is not positive")
        # Tick/step/min-notional are applied by Hummingbot Connector quantization in the Worker.
        return notional / mid

    async def _cancel_opening_orders(self, session: AsyncSession) -> bool:
        canceled = True
        for order in await OrderRepository(session).list_open():
            if order.reduce_only:
                continue
            request_id = new_id()
            try:
                viewed = await self._execution.cancel_order(order.cloid, request_id)
            except Exception:
                order.status = OrderStatus.UNKNOWN.value
                canceled = False
                continue
            if viewed:
                order.status = viewed.status.value
        await session.commit()
        return canceled

    async def _cancel_all_orders(self, session: AsyncSession) -> bool:
        canceled = True
        for order in await OrderRepository(session).list_open():
            request_id = new_id()
            try:
                viewed = await self._execution.cancel_order(order.cloid, request_id)
            except Exception:
                order.status = OrderStatus.UNKNOWN.value
                canceled = False
                continue
            if viewed:
                order.status = viewed.status.value
        await session.commit()
        return canceled

    async def _emit(self, session: AsyncSession, event_type: str, payload: dict) -> None:
        event = await EventRepository(session).add(event_type, json.dumps(payload, default=str))
        await session.commit()
        await self._hub.publish(event_type, payload, event.id)
