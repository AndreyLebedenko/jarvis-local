# MCP SDK logs an error while closing an open SSE stream

Detected in Windows GitHub CI. Local HEAD at triage was `d98fa12`.

`test_stopping_with_an_open_session_stream_is_fast_clean_and_frees_the_port`
passed the time assertion and failed on an ERROR record from MCP's standalone
SSE writer. Its traceback shows `anyio.ClosedResourceError` during session
termination.

The SDK closes the receive stream while its SSE writer is waiting on it.
The SDK reports the exception as an error. The upstream report also identifies
AnyIO 4.16.0 as a version that makes the blocked reader wake on close.

Keep the shutdown assertion and the project's SDK range while the upstream
issue is open. Downgrading MCP would lose the session bounds used by Jarvis,
and filtering the record would leave the shutdown behavior in the dependency.
Recheck the existing open-stream test when a compatible SDK release carries
the fix. The migration to SDK 2.x has its own backlog task.

[MCP Python SDK issue #3833](https://github.com/modelcontextprotocol/python-sdk/issues/3833)
