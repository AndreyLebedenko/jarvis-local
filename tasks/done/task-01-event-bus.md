# Task: Event bus (bus.py)

Status: Completed.

Story: [story-jarvis-v1.0.md](story-jarvis-v1.0.md)

## Summary

An asyncio pub/sub event bus. This is the sole inter-module communication
mechanism for the whole project (PROJECT.md: "no direct module-to-module
calls") and the extension point for everything later (emotion side-channel,
Discord bridge, etc.). Must stay trivial.

## Current boundary

In scope:

- Async-safe publish/subscribe API: subscribe to an event type/topic,
  publish an event, deliver to all current subscribers.
- Unsubscribe.
- Multiple subscribers per event type; a publish with zero subscribers is a
  no-op, not an error.
- Concurrent publish from multiple coroutines without lost or duplicated
  deliveries.
- Bus is type-agnostic: it moves arbitrary payload objects. Event payload
  schemas (e.g. a wav-chunk event, a screenshot event, a sentence event) are
  defined by the producing module when that module is built, not here.

Out of scope:

- No persistence, replay, or cross-process transport.
- No built-in event type definitions - those belong to the modules that
  produce them (task-03 onward).
- No priority/ordering guarantees beyond per-subscriber delivery order.

## Dependencies

None. Pure asyncio + stdlib. Every later module depends on this one.

## Acceptance criteria

Automated tests only (pure logic, no hardware):

- Subscribing and publishing delivers the event to all subscribers.
- Unsubscribing stops further delivery to that subscriber.
- Two different event types never cross-deliver to each other's
  subscribers.
- Publishing with no subscribers does not raise.
- Concurrent publishes from multiple coroutines deliver every event exactly
  once per subscriber (no loss, no duplication).
- The module has no import dependency on any other project module.
