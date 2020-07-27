# -*- coding: utf-8 -*-
'''
@author: Manuel Boissenin, Yann Cointepas, Denis Riviere

@organization: NAO, UNATI, Neurospin, Gif-sur-Yvette, France

'''
from __future__ import print_function
from __future__ import absolute_import

try:
    import six.moves.cPickle as pickle
except ImportError:
    import pickle
import traceback
import zmq
import logging
import threading
import sys
import weakref
import time

# For some reason the zmq bind_to_random_port did not work with
# one of the version of zmq that we are using. Therfore we have
# to use the followin function:

import socket
from contextlib import closing


def find_free_port():
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(('', 0))
        return s.getsockname()[1]


class ReturnException(object):

    ''' Fake exception, wraps an exception occuring during server-side
        execution.

        ReturnException cannot be an Exception subclass because it causes
        problems in pickling (in unpickling, actually). In the same idea,
        the exception traceback cannot be a "real" traceback because a
        traceback cannot be pickled. We use a string representation of it
        instead (using traceback.format_exc()).
    '''

    def __init__(self, e, exc_info):
        self.exc = e
        self.exc_info = exc_info  # a tuple (exc_type, exc_value, traceback)


class ObjectServer(object):

    '''
    Usage:
    -create an ObjectServer providing a port.
    -register the object you want to access from another
     program that might be on a distant object.
    -lauch the server loop.
    '''

    def __init__(self, port=None):
        self.objects = {}
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.REP)
        if not port:
            port = find_free_port()
            # try:
            # Here there is a bug probably linked with the zmq version
            #     port = self.socket.bind_to_random_port("tcp://*:",
            #                                            min_port=1025,
            #                                            max_port=65536,
            #                                            max_tries=1200)
            # except Exception as e:
            #     logging.debug("Maximum number of attempt to find a port reached?: " + str(e))
        # else:
        self.socket.bind("tcp://*:" + str(port))
        self.port = port
        logger = logging.getLogger('database.ObjectServer')
        logger.debug("Initialising object server on port: " + repr(self.port))

    def register(self, object):
        """The full socket adress should be provided
        what if we have multiple object of one given class
        (the identifier of the object could be used and the uri should be changed)
        """
        if object.__class__.__name__ not in self.objects:
            self.objects[object.__class__.__name__] = {}
        self.objects[object.__class__.__name__][str(id(object))] = object

        logger = logging.getLogger('database.ObjectServer')
        logger.debug("The oject server is registering a "
                     + repr(object.__class__.__name__)
                     + "object, on " + repr(self.port))

        return str(object.__class__.__name__) + ":" + str(id(object)) + ":" + str(self.port)

    def serve_forever(self):
        logger = logging.getLogger('database.ObjectServer')
        # logger.setLevel(logging.DEBUG)
        while True:
            #  Wait for next request from client
            logger.debug("ObS0:" + str(self.port)[-3:]
                         + ":Waiting for incoming data")
            try:
                message = self.socket.recv()
            except Exception as e:
                logger.exception(e)
                raise  # communication error, exit loop
            try:
                classname, object_id, method, args, kwargs = pickle.loads(
                    message)
                logger.debug("ObS1:" + str(self.port)[-3:] + ":calling "
                             + classname + " " + object_id + " " + method
                             + " " + repr(args))
                try:
                    if self.objects[classname][object_id]:
                        result = getattr(
                            self.objects[classname][object_id], method)(*args, **kwargs)
                    else:
                        pass  # TODO
                        # logging.debug("object not in the list of objects")
                except Exception as e:
                    logger.exception(e)
                    etype, evalue, etb = sys.exc_info()
                    if hasattr(e, 'server_traceback'):
                        logger.error('server-side traceback:\n'
                                     + e.server_traceback)
                        evalue.server_traceback = traceback.format_exc() \
                            + '\nremote server traceback:\n' \
                            + e.server_traceback
                    else:
                        evalue.server_traceback = traceback.format_exc()
                    result = ReturnException(e, (etype, evalue,
                                                 traceback.format_exc()))
                logger.debug("ObS2:" + str(self.port)[-3:] + ":result is: "
                             + repr(result))
                self.socket.send(pickle.dumps(result))
            except Exception as e:
                logger.exception(e)
                # print("An exception occurred in the server of the remote object")
                # traceback.print_exc()


class Proxy(object):

    """
    The Proxy object is created with the uri of the object
    afterwards you can call any method you want on it,
    to access variable attributes you will have to create properties (accessors)
    """

    def __init__(self, uri):
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.REQ)
        # To avoid multiple threads using the socket at the same time
        self.lock = threading.RLock()
        # Deux cas: ou uri est un bytes object ou il est du type str
        if type(uri) == type(b'bytes type'):
            (classname, object_id, self._port) = uri.split(b':')
            # caveat: note that connect will succeed even if there is
            # no port waiting for a connection, as such you have to
            # check yourself that the connection has succeeded
            # (cf how the database server engine is handled
            self.classname = classname.decode('utf-8')
            self.object_id = object_id.decode('utf-8')
            self.socket.connect(
                "tcp://localhost:" + self._port.decode('utf-8'))
        elif type(uri) == type("str type"):
            (self.classname, self.object_id, self._port) = uri.split(':')
            # caveat: note that connect will succeed even if there is
            # no port waiting for a connection, as such you have to
            # check yourself that the connection has succeeded
            # (cf how the database server engine is handled
            self.socket.connect("tcp://localhost:" + self._port)
        elif type(uri) == type(u"unicode type"):
            (self.classname, self.object_id, self._port) = uri.split(':')
            # caveat: note that connect will succeed even if there is
            # no port waiting for a connection, as such you have to
            # check yourself that the connection has succeeded
            # (cf how the database server engine is handled
            self.socket.connect("tcp://localhost:" + self._port)
        else:
            print("Issue in zro: the uri is not taken into account, "
                  "this is probably due to its type")
        logger = logging.getLogger('database.ObjectServer')
        logger.debug("Proxy: " + str(self.classname) + str(self.object_id)
                     + str(self._port))
        # TODO
        # logging.debug(self.classname, self.object_id, self._port)
        self.timeout = -1
        self.running_methods = set()

    def __del__(self):
        # kill all running methods because the proxy / connection is destroyed.
        print('del Proxy', self.classname, self)
        def get_running(self):
            with self.lock:
                if self.running_methods:
                    return next(iter(self.running_methods))
                return None
        while True:
            method = get_running(self)
            if method is None:
                break
            print('    interrupt method:', method.method)
            method.interrupt()

    def __getattr__(self, method_name):
        if method_name in self.__dict__:
            return self.__dict__[method_name]
        logger = logging.getLogger('database.ObjectServer')
        logger.debug("On class:               " + self.classname)
        logger.debug("method called:          " + method_name)
        with self.lock:
            method = ProxyMethod(self, method_name)
            self.running_methods.add(method)
        return method

    def interrupt_after(self, timeout):
        with self.lock:
            self.timeout = timeout


class ProxyMethod(object):

    def __init__(self, proxy, method):
        self.proxy = weakref.proxy(proxy)
        self.method = method
        self.stop_request = False

    def __call__(self, *args, **kwargs):
        try:
            timeout = 2000  # ms
            logger = logging.getLogger('database.ObjectServer')
            #self.proxy.lock.acquire()
            with self.proxy.lock:
                try:
                    self.proxy.socket.send(
                        pickle.dumps([self.proxy.classname, self.proxy.object_id, self.method, args, kwargs]))
                except Exception as e:
                    logger.exception(e)
                    print("Exception occurred while calling a remote object: %s.%s(*%s, **%s)"
                          % (self.proxy.classname, self.method, repr(args),
                          repr(kwargs)))
                    print(e)
            done = False
            t0 = time.time()
            while not done:
                with self.proxy.lock:
                    poll_res = self.proxy.socket.poll(timeout, zmq.POLLIN)
                if poll_res:
                    done = True
                    with self.proxy.lock:
                        msg = self.proxy.socket.recv(zmq.NOBLOCK)
                with self.proxy.lock:
                    if self.stop_request or (self.proxy.timeout >= 0 \
                            and time.time() - t0 > self.proxy.timeout):
                        done = True
                        raise RuntimeError(
                            'Connection timeout in ProxyMethod.__call__ for: %s.%s(*%s, **%s)'
                            % (self.proxy.classname, self.method, repr(args),
                              repr(kwargs)))
            result = pickle.loads(msg)
            logger.debug("remote call result:     " + str(result))

            if isinstance(result, ReturnException):
                logger.error('ZRO proxy returned an exception: '
                            + str(result.exc_info[1]))
                logger.error(''.join(traceback.format_stack()))
                if hasattr(result.exc_info[1], 'server_traceback'):
                    logger.error('exception remote traceback:'
                                + result.exc_info[1].server_traceback)
                else:
                    logger.error('exception traceback: '
                                + str(result.exc_info[2]))
                raise result.exc_info[1]

            return result

        finally:
            with self.proxy.lock:
                self.proxy.running_methods.remove(self)
                if self.stop_request:
                    self.stop_request = False

    def interrupt(self):
        with self.proxy.lock:
            self.stop_request = True
        done = False
        while not done:
            with self.proxy.lock:
                if not self.stop_request:
                    done = True
