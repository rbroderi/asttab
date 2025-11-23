from collections.abc import AsyncGenerator
from typing import Any


async def async_yield_from(
    __async_yf_source: AsyncGenerator[Any, Any],
) -> AsyncGenerator[Any, Any]:
    try:
        __async_yf_current = await __async_yf_source.__anext__()
    except StopAsyncIteration:
        return
    else:
        while True:
            try:
                __async_yf_sent_in = yield __async_yf_current

            except GeneratorExit as __async_yf_ge:
                # The outer async generator is being closed (via aclose()).
                # Propagate closure to the inner async generator if supported.
                try:
                    __async_yf_aclose = __async_yf_source.aclose
                except AttributeError:
                    pass
                else:
                    await __async_yf_aclose()
                raise __async_yf_ge

            except BaseException as __async_yf_exc:
                # Forward exceptions into inner async generator via athrow()
                __async_yf_athrow = getattr(__async_yf_source, "athrow", None)
                if __async_yf_athrow is None:
                    raise
                try:
                    __async_yf_current = await __async_yf_athrow(__async_yf_exc)
                except StopAsyncIteration:
                    return

            else:
                try:
                    if __async_yf_sent_in is None:
                        __async_yf_current = await __async_yf_source.__anext__()
                    else:
                        __async_yf_asend = getattr(__async_yf_source, "asend", None)
                        if __async_yf_asend is None:
                            __async_yf_current = await __async_yf_source.__anext__()
                        else:
                            __async_yf_current = await __async_yf_asend(
                                __async_yf_sent_in
                            )
                except StopAsyncIteration:
                    return
