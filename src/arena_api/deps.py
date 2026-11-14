from arq.connections import ArqRedis
from fastapi import Request


def get_queue(request: Request) -> ArqRedis:
    """The job queue's Redis connection. Its own module so that routes and limiters can both use it
    without importing each other."""
    queue: ArqRedis = request.app.state.queue
    return queue
