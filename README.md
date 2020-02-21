# Kubeless Async Python Runtime

This [repo] provides [kubeless] python runtime with ayncio. It uses [tornado] as web server. Currently the Python version is 3.8.1. The docker images is under [kazimsarikaya/kubeless-runtimes-python:3.8-async]. You can pull with:

```
docker pull kazimsarikaya/kubeless-runtimes-python:3.8-async
```

Each function is defined by:

```
async def func_name(event, context)
  return "hello world from asyncio"
```

The event object provides a underling tornado handler with ```event['extensions']['handler']```. Also you can set a callback function with ```event['extensions']['callback']``` and it will be executed after response send to the clients. It can be defined as async or sync. It has one argument which is status of response

```
async def func_name(event, context)
  async def cb(status):
    pass
  event['extensions']['callback'] = cb
  return "hello world from asyncio"
```

While using **asyncio**, cpu intensive functions should be run inside an executor. The runtime provides a ThreadPoolExecutor interface with ```event['extensions']['executor']```. The thread count is defined as ```cpu_core_count*___THREAD_MULTIPLIER```. The ```___THREAD_MULTIPLIER``` is an environment variable and default value is **4**.

```
async def cpu_intensive(event, context):
  def cpufunc(s):
    from time import sleep, time
    sleep(s)
    return time()

  executor = event["extensions"]["executor"]
  t = await executor(cpufunc, 2)
  return {"time": t}
```

[kubeless]: https://kubeless.io
[tornado]: https://www.tornadoweb.org
[kazimsarikaya/kubeless-runtimes-python:3.8-async]: https://hub.docker.com/r/kazimsarikaya/kubeless-runtimes-python
[repo]: https://github.com/kazimsarikaya/kubeless-runtimes-python
