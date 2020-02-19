#!/usr/bin/env python

import os
import importlib.machinery
import importlib.util
import prometheus_client as prom
import asyncio
from tornado.web import Application, RequestHandler, URLSpec
from tornado.httpserver import HTTPServer
from tornado.ioloop import IOLoop
import json
import time
import logging
import sys

loader = importlib.machinery.SourceFileLoader(
    'function',
    '/kubeless/%s.py' % os.getenv('MOD_NAME'))
spec = importlib.util.spec_from_loader(loader.name, loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)


func = getattr(mod, os.getenv('FUNC_HANDLER'))
func_port = os.getenv('FUNC_PORT', 8080)

timeout = float(os.getenv('FUNC_TIMEOUT', 180))

func_hist = prom.Histogram('function_duration_seconds',
                           'Duration of user function in seconds',
                           ['method'])
func_calls = prom.Counter('function_calls_total',
                          'Number of calls to user function',
                          ['method'])
func_errors = prom.Counter('function_failures_total',
                           'Number of exceptions in user function',
                           ['method'])

function_context = {
    'function-name': func,
    'timeout': timeout,
    'runtime': os.getenv('FUNC_RUNTIME', "python3.8"),
    'memory-limit': os.getenv('FUNC_MEMORY_LIMIT', "0"),
}


class HealthzHandler(RequestHandler):
    async def get(self):
        self.write('OK')
        self.finish()


class MetricsHandler(RequestHandler):
    async def get(self):
        self.write(prom.generate_latest(prom.REGISTRY))
        self.set_header("Content-Type", prom.CONTENT_TYPE_LATEST)
        self.finish()


class FunctionHandler(RequestHandler):

    def prepare(self):
        ct = self.request.headers.get('Content-Type', None)
        self.data = self.request.body
        if not (ct is None):
            if ct == 'application/json':
                self.data = json.loads(self.data, "utf-8")

    async def get(self):
        return await self.handler()

    async def post(self):
        return await self.handler()

    async def put(self):
        return await self.handler()

    async def delete(self):
        return await self.handler()

    async def handler(self):
        event = {
            'data': self.data,
            'event-id': self.request.headers.get('event-id', ''),
            'event-type': self.request.headers.get('event-type', ''),
            'event-time': self.request.headers.get('event-time', time.time()),
            'event-namespace': self.request.headers.get('event-namespace', ''),
            'extensions': {
                'request': self.request,
                'callback': None
            }
        }
        method = self.request.method
        self.callback = None
        func_calls.labels(method).inc()
        with func_hist.labels(method).time():
            try:
                res = await asyncio.wait_for(
                    func(event, function_context), timeout=timeout)
            except asyncio.TimeoutError:
                self.callback = event["extensions"]["callback"]
                func_errors.labels(method).inc()
                self.clear()
                self.set_status(408)
                self.finish({"reason":
                             "Timeout while processing the function"})
            else:
                self.callback = event["extensions"]["callback"]
                if isinstance(res, Exception):
                    func_errors.labels(method).inc()
                    self.clear()
                    self.set_status(408)
                    self.finish({"reason":  res})

                self.finish(res)

    def on_finish(self):
        if not (self.callback is None):
            self.callback(status=self.get_status())


if __name__ == '__main__':
    access_log = logging.getLogger('tornado.access')
    access_log.propagate = False
    access_log.setLevel(logging.INFO)
    stdout_handler = logging.StreamHandler(sys.stdout)
    access_log.addHandler(stdout_handler)
    routes = [
        URLSpec(r'/healthz', HealthzHandler),
        URLSpec(r"/metrics", MetricsHandler),
        URLSpec(r"/", FunctionHandler)
    ]

    app = Application(routes)
    server = HTTPServer(app)
    server.bind(func_port, reuse_port=True)
    server.start()
    io_loop = IOLoop().current()
    io_loop.start()
