#!/usr/bin/env python

from argparse import ArgumentParser
from argparse import RawDescriptionHelpFormatter
import logging
import textwrap
from cif.constants import CTRL_ADDR, ROUTER_ADDR, STORAGE_ADDR, HUNTER_ADDR

from pprint import pprint
import zmq
from zmq.eventloop import ioloop
import json
import time
from cif.utils import setup_logging, get_argument_parser, setup_signals


class Router(object):

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        self.stop()

    def __init__(self, listen=ROUTER_ADDR, hunter=HUNTER_ADDR, storage=STORAGE_ADDR):
        self.logger = logging.getLogger(__name__)

        self.context = zmq.Context.instance()
        self.frontend = self.context.socket(zmq.ROUTER)
        self.storage = self.context.socket(zmq.DEALER)
        self.hunters = self.context.socket(zmq.PUB)
        self.ctrl = self.context.socket(zmq.REP)

        self.poller = zmq.Poller()

        self.ctrl.bind(CTRL_ADDR)
        self.frontend.bind(listen)
        self.hunters.bind(hunter)
        self.storage.bind(storage)

    def auth(self, token):
        if not token:
            return 0
        return 1

    def handle_ctrl(self, s, e):
        self.logger.debug('ctrl msg recieved')
        id, mtype, data = s.recv_multipart()

        self.ctrl.send_multipart(['router', 'ack', str(time.time())])

    def handle_message(self, s, e):
        self.logger.debug('message received')
        m = s.recv_multipart()

        id, null, token, mtype, data = m
        self.logger.debug("mtype: {0}".format(mtype))

        if self.auth(token):
            handler = getattr(self, "handle_" + mtype)
            self.logger.debug('handler: {}'.format(handler))
            rv = handler(token, data)
        else:
            self.logger.debug('auth failed...')
            rv = json.dumps({
                "status": "failed",
                "data": "unauthorized"
            })

        self.logger.debug("replying {}".format(rv))
        self.frontend.send_multipart([id, '', mtype, rv])

    def handle_ping(self, token, data):
        self.logger.info('sending to hunters..')
        rv = {
            "status": "success",
            "data": str(time.time())
        }
        return json.dumps(rv)

    def handle_write(self, data):
        rv = {
            "status": "failed",
            "data": str(time.time())
        }
        return json.dumps(rv)

    def handle_search(self, token, data):
        self.storage.send_multipart(['search', token, data])
        return self.storage.recv()

    def handle_submission(self, token, data):
        self.hunters.send(data)
        self.storage.send_multipart(['submission', token, data])
        m = self.storage.recv()
        return m

    def run(self):
        self.logger.debug('starting loop')
        loop = ioloop.IOLoop.instance()
        loop.add_handler(self.frontend, self.handle_message, zmq.POLLIN)
        loop.add_handler(self.ctrl, self.handle_ctrl, zmq.POLLIN)
        loop.start()

    def stop(self):
        return self


def main():
    p = get_argument_parser()
    p = ArgumentParser(
        description=textwrap.dedent('''\
        Env Variables:
            CIF_RUNTIME_PATH
            CIF_ROUTER_ADDR
            CIF_HUNTER_ADDR
            CIF_STORAGE_ADDR

        example usage:
            $ cif-router --listen 0.0.0.0 -d
        '''),
        formatter_class=RawDescriptionHelpFormatter,
        prog='cif-router',
        parents=[p]
    )

    p.add_argument('--listen', help='address to listen on [default: %(default)s]', default=ROUTER_ADDR)
    p.add_argument('--hunter', help='address hunters listen on on [default: %(default)s]', default=HUNTER_ADDR)
    p.add_argument("--storage", help="specify a storage address [default: %(default)s]",
                   default=STORAGE_ADDR)

    args = p.parse_args()
    setup_logging(args)
    logger = logging.getLogger(__name__)
    logger.info('loglevel is: {}'.format(logging.getLevelName(logger.getEffectiveLevel())))

    setup_signals(__name__)

    with Router(listen=args.listen, hunter=args.hunter, storage=args.storage) as r:
        try:
            logger.info('starting router..')
            r.run()
        except KeyboardInterrupt:
            logger.info('shutting down...')

    logger.info('Shutting down')

if __name__ == "__main__":
    main()
