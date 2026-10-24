"""A scripted stand-in for the model backend: replies are given in call order and the
last one repeats; an exception in the list is raised instead of returned."""

from __future__ import annotations


class FakeBackend:
    def __init__(self, *replies):
        self._replies = list(replies)
        self.requests = []

    async def complete(self, request):
        self.requests.append(request)
        reply = self._replies[min(len(self.requests), len(self._replies)) - 1]
        if isinstance(reply, BaseException):
            raise reply
        return reply
