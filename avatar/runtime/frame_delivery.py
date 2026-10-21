"""Incremental inference with a bounded two-frame bridge and joined cleanup."""
import asyncio
import concurrent.futures
import threading


async def iter_frames(iterator):
    loop=asyncio.get_running_loop()
    queue=asyncio.Queue(maxsize=2)
    stop=threading.Event()

    def put(kind,value):
        if stop.is_set():return False
        future=asyncio.run_coroutine_threadsafe(queue.put((kind,value)),loop)
        while not stop.is_set():
            try:future.result(timeout=.1);return True
            except concurrent.futures.TimeoutError:pass
        future.cancel()
        return False

    def produce():
        try:
            for frame in iterator:
                if not put('frame',frame):break
        except Exception as error:
            put('error',error)
        finally:
            iterator.close()
            put('done',None)

    worker=asyncio.create_task(asyncio.to_thread(produce))
    try:
        while True:
            kind,value=await queue.get()
            if kind=='done':return
            if kind=='error':raise value
            yield value
    finally:
        stop.set()
        # Finish the in-flight worker before another session can use its engine.
        await worker


async def deliver_frames(frames,send):
    stream=iter_frames(frames)
    try:
        async for frame in stream:
            await send(frame)
    finally:
        await stream.aclose()
