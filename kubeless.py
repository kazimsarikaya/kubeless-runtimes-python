#!/usr/bin/env python


# Kubeless Async Python Runtime
# Copyright (C) 2020  Kazım SARIKAYA <kazimsarikaya@sanaldiyar.com>
#
# This file is part of Kubeless Async Python Runtime.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.


import os
import signal
import importlib.machinery
import importlib.util
import prometheus_client as prom
import asyncio
from tornado.web import Application, RequestHandler, URLSpec
from tornado.httpserver import HTTPServer
from tornado.ioloop import IOLoop, PeriodicCallback
import tornado.options as tornado_options
import json
import time
import logging
import multiprocessing
from concurrent.futures import ThreadPoolExecutor
from functools import partial
import uvloop

logger = logging.getLogger("kubeless")

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


class Executor:

    def __init__(self):
        self.cpu_count = multiprocessing.cpu_count()
        self.tpexecutor = ThreadPoolExecutor(
            self.cpu_count * int(os.getenv('___THREAD_MULTIPLIER', 4)),
            "kptpe-%s.%s-" % (os.getenv('MOD_NAME'),
                              os.getenv('FUNC_HANDLER'),))

    def __call__(self, func, *args, **kwargs):
        loop = asyncio.get_event_loop()
        return loop.run_in_executor(self.tpexecutor,
                                    partial(func, *args, **kwargs))


executor = Executor()


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
                try:
                    self.data = json.loads(self.data.decode("utf-8"))
                except Exception as e:
                    logger.error("error at parsing body as json: %s" % (e,))
                    func_errors.labels(self.request.method).inc()
        self.event = {
            'data': self.data,
            'event-id': self.request.headers.get('event-id', ''),
            'event-type': self.request.headers.get('event-type', ''),
            'event-time': self.request.headers.get('event-time', time.time()),
            'event-namespace': self.request.headers.get('event-namespace', ''),
            'extensions': {
                'handler': self,
                'callback': None,
                'executor': executor
            }
        }

    async def get(self):
        return await self.handler()

    async def post(self):
        return await self.handler()

    async def put(self):
        return await self.handler()

    async def delete(self):
        return await self.handler()

    async def options(self):
        return await self.handler()

    async def handler(self):
        func_calls.labels(self.request.method).inc()
        with func_hist.labels(self.request.method).time():
            try:
                res = await asyncio.wait_for(
                    func(self.event, function_context), timeout=timeout)
            except asyncio.TimeoutError as e:
                logger.error("timeout occured: %s" % (e,))
                func_errors.labels(self.request.method).inc()
                self.clear()
                self.set_status(408)
                self.finish({"reason":
                             "Timeout while processing the function"})
            except Exception as e:
                logger.error("general error at function execution: %s" % (e,))
                func_errors.labels(self.request.method).inc()
                self.clear()
                self.set_status(500)
                self.finish({"reason":
                             "General error while processing the function"})
            else:
                if isinstance(res, Exception):
                    logger.error("error at function execution: %s" % (res,))
                    func_errors.labels(self.request.method).inc()
                    self.clear()
                    self.set_status(500)
                    self.finish({"reason": "%s" % (res,)})
                else:
                    self.finish(res)

    def on_finish(self):
        try:
            callback = self.event["extensions"]["callback"]
            if not (callback is None):
                if asyncio.iscoroutinefunction(callback):
                    asyncio.gather(
                        callback(self.get_status()))
                else:
                    callback(self.get_status())
        except Exception as e:
            logger.error("error at callback execution: %s" % (e,))
            func_errors.labels(self.request.method).inc()


class KubelessApplication(Application):
    is_closing = False

    def signal_handler(self, signum, frame):
        logger.info('exiting...')
        self.is_closing = True

    def try_exit(self):
        if self.is_closing:
            IOLoop.instance().stop()
            logger.info('exit success')


if __name__ == '__main__':
    tornado_options.parse_command_line()

    routes = [
        URLSpec(r'/healthz', HealthzHandler),
        URLSpec(r"/metrics", MetricsHandler),
        URLSpec(r"/", FunctionHandler)
    ]

    logger.info("Server is starting")
    loop = uvloop.new_event_loop()
    asyncio.set_event_loop(loop)
    io_loop = IOLoop().current()
    app = KubelessApplication(routes)
    server = HTTPServer(app)
    server.bind(func_port, reuse_port=True)
    server.start()
    signal.signal(signal.SIGINT, app.signal_handler)
    signal.signal(signal.SIGTERM, app.signal_handler)
    PeriodicCallback(app.try_exit, 100).start()
    io_loop.start()
