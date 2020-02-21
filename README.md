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

# Kubeless Configuration

For using with kubeless, you should add this runtime to runtimes array at configmap kubeless-config at kubeless namespace such as:

```
{
  "ID": "python-async",
  "depName": "requirements.txt",
  "fileNameSuffix": ".py",
  "versions": [{
    "images": [{
      "command": "pip install --prefix=$KUBELESS_INSTALL_VOLUME -r $KUBELESS_DEPS_FILE",
      "image": "kazimsarikaya/kubeless-runtimes-python@sha256:0648af8ff2aa205be5c96c6ccb7477c92f1c154a57317a74af9fc91a9f19ee42",
      "phase": "installation"
    }, {
      "env": {
        "PYTHONPATH": "$(KUBELESS_INSTALL_VOLUME)/lib/python3.8/site-packages:$(KUBELESS_INSTALL_VOLUME)"
      },
      "image": "kazimsarikaya/kubeless-runtimes-python@sha256:0648af8ff2aa205be5c96c6ccb7477c92f1c154a57317a74af9fc91a9f19ee42",
      "phase": "runtime"
    }],
    "name": "python-async3.8",
    "version": "3.8"
  }]
}
```

You should delete kubeless controller pod to activate new config. And then, you can define your function as with using new runtime **python-async3.8**:

```
apiVersion: kubeless.io/v1beta1
kind: Function
metadata:
  name: get-python
  namespace: playground
  label:
    created-by: kubeless
    function: get-python
spec:
  runtime: python-async3.8
  timeout: "180"
  handler: helloget.foo
  deps: ""
  function-content-type: text
  function: |
    async def foo(event, context):
      return "hello world"

  service:
    ports:
    - name: http-function-port
      port: 80
      protocol: TCP
      targetPort: 8080
    selector:
      created-by: kubeless
      function: get-python
```

# Updates

You should update image sha of the runtime at kubeless configmap for updates. Then restart kubeless controller. For updating the image used by your function is done by updating deployment of that function (changing the image).

[kubeless]: https://kubeless.io
[tornado]: https://www.tornadoweb.org
[kazimsarikaya/kubeless-runtimes-python:3.8-async]: https://hub.docker.com/r/kazimsarikaya/kubeless-runtimes-python
[repo]: https://github.com/kazimsarikaya/kubeless-runtimes-python
