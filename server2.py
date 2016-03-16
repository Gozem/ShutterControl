import tornado.httpserver
import tornado.ioloop
import tornado.options
import tornado.web
import tornado.websocket

import time
import Queue
import threading

 
from tornado.options import define, options
define("port", default=9000, help="run on the given port", type=int)
 
class IndexHandler(tornado.web.RequestHandler):
    def get(self):
        self.render('index2.html')
 
wsClients = []
class WebSocketHandler(tornado.websocket.WebSocketHandler):
    def open(self):
        print 'new connection'
        self.write_message("connected")
        if self not in wsClients:
            wsClients.append(self)
 
    def on_message(self, message):
        print 'message received %s' % message


        data = message.split(";")
        cmd = data[0]
        args = data[1:]
        print cmd
        print args

        s = self.application.settings.get('shutter')

        if cmd == "UP":
            for arg in args:
                print "arg: " + arg
                
            s.up()

        elif cmd == "DOWN":
            s.down()

        elif cmd == "STOP":
            s.stop()

        elif cmd == "FORCEUP":
            s.forceUp()

        elif cmd == "FORCEDOWN":
            s.forceDown()

        else:
            print "Unknown command '%s' from client" % cmd
        
    def on_close(self):
        print 'connection closed'
        if self in wsClients:
            wsClients.remove(self)


def getNow():
    return int(time.time())        

class Pin:
    _status = None

    def __init__(self, name, pin):
        self._name = name
        self._pin = pin
    
    def on(self):
        if self._status == True:
            return

        print "%s pin=%d ON" % (self._name, self._pin)
        self._status = True

    def off(self):
        if self._status == False:
            return

        print "%s pin=%d OFF" % (self._name, self._pin)
        self._status = False



class State:
    UNINITED = 0
    OPEN = 1
    CLOSED = 2
    STOPPED = 3
    GOING_DOWN = 11
    GOING_UP = 12

    @staticmethod
    def toString(state):
        if state == State.UNINITED:
            return "UNINITED"
        elif state == State.OPEN:
            return "OPEN"
        elif state == State.CLOSED:
            return "CLOSED"
        elif state == State.STOPPED:
            return "STOPPED"
        elif state == State.GOING_DOWN:
            return "GOING_DOWN"
        elif state == State.GOING_UP:
            return "GOING_UP"
        else:
            return "UNKNOWN"


class Command:
    NOCMD = 0
    DOWN = 1
    UP = 2
    STOP = 3
    FORCEUP = 4
    FORCEDOWN = 5



class Shutter:
    _state = State.UNINITED
    _nextCmd = Command.NOCMD
    _cmdDoneAt = getNow()
    _active = False

    def _log(self, msg):
        print "%s %s" % (self._name, msg)

    def _runStateChangeCallback(self):
        self._onStateChangeCallback(self, self._name, self._state, self._active)        

    def _setState(self, state):
        self._state = state

    def _setNextCmd(self, cmd):
        self._nextCmd = cmd # Overwrite any waiting command

    def _running(self):
        # Run up or down for 30 seconds
        self._cmdDoneAt = getNow() + 7
        self._active = True
        self._runStateChangeCallback()

    def _pause(self):
        # Wait 2 seconds before we accept next command so motor doesn't
        # alter direction too fast
        self._cmdDoneAt = getNow() + 2
        self._active = True
        self._runStateChangeCallback()

    def _down(self):
        self._log("Going down")
        self._downPin.on()
        self._setState(State.GOING_DOWN)
        self._running()

    def _up(self):
        self._log("Going up")
        self._upPin.on()
        self._setState(State.GOING_UP)
        self._running()

    def _stop(self):
        self._downPin.off()
        self._upPin.off()
        self._setState(State.STOPPED)
        self._setNextCmd(Command.NOCMD)
        self._pause()

    def __init__(self, name, downPin, upPin, onStateChangeCallback):
        self._name = name
        self._downPin = downPin
        self._upPin = upPin
        self._onStateChangeCallback = onStateChangeCallback

        #Init state, UP = off, run down
        self._upPin.off()
        self._down()

    def down(self):
        self._log("Command down")
        if getNow() <= self._cmdDoneAt:
            self._stop() # Abort current
            self._setNextCmd(Command.DOWN)
        elif self._state != State.CLOSED:
            self._down()

    def up(self):
        self._log("Command up")
        if getNow() <= self._cmdDoneAt:
            self._stop() # Abort current
            self._setNextCmd(Command.UP)
        elif self._state != State.OPEN:
            self._up()        

    def stop(self):
        self._log("Command stop")
        self._stop()

    def forceDown(self):
        self._log("Command forceDown")
        self._upPin.off()
        self._down()
        self._setNextCmd(Command.NOCMD)

    def forceUp(self):
        self._log("Command forceUp")
        self._downPin.off()
        self._up()
        self._setNextCmd(Command.NOCMD)

    def process(self):
        # Called each second

        if self._active == False:
            return

        if getNow() < self._cmdDoneAt:
            print "Still running"
            return # Still running a command

        # No command running, stop motor
        self._downPin.off()
        self._upPin.off()
        self._active = False

        if self._state == State.GOING_DOWN:
            self._setState(State.CLOSED)
            self._pause()

        elif self._state == State.GOING_UP:
            self._setState(State.OPEN)
            self._pause()     

        else:
            # We can process next command
            if self._nextCmd == Command.UP:
                self._nextCmd = Command.NOCMD
                if self._state != State.OPEN:
                    self._up()

            elif self._nextCmd == Command.DOWN:
                self._nextCmd = Command.NOCMD
                if self._state != State.CLOSED:
                    self._down()
            
            else:
                # Nothing more todo, we are inactive and waiting for next cmd
                self._runStateChangeCallback()


class ShutterServer(threading.Thread):
    _rain = False
    _shutter = ['not used', # We have shutter 1-6, not 0-5
                State.UNINITED, 
                State.UNINITED, 
                State.UNINITED,
                State.UNINITED,
                State.UNINITED,
                State.UNINITED]

    def __init__(self, cmdQ, statusQ):
        threading.Thread.__init__(self)
        self.cmdInQ = cmdQ       # Input command queue
        self.statusOutQ = statusQ # Output status queue

    def run(self):
        print "ShutterServer running!"
        while True:
            msg = self.cmdInQ.get() # Blocks forever until command received
            
            print "MSG: " + msg
            print self._shutter

            data = msg.split(";")
            cmd = data[0]
            args = data[1:]
            print cmd
            print args

            if cmd == "UP":
                for arg in args:
                    print "shutters: " + arg
            else:
                print "Unknown command '%s'" % cmd

            self.cmdInQ.task_done()
            

 
if __name__ == "__main__":

    _isOpen = set()
    _isClosed = set()
    
    def wsSendAll(message):
        for client in wsClients:
            client.write_message(message)

    def shutterStateChange(shutter, name, state, active):
        msg = name + "_" + State.toString(state) + "_" + str(active)
        print "Callback: " + msg
        wsSendAll(msg)

        _isOpen.discard(shutter)
        _isClosed.discard(shutter)
        if state == State.OPEN or state == State.GOING_UP:
            _isOpen.add(shutter)
        elif state == State.CLOSED or state == State.GOING_DOWN:
            _isClosed.add(shutter)

        print _isOpen
        print _isClosed

    tornado.options.parse_command_line()


    print "starting shutterserver"
    cmdQ = Queue.Queue()
    statusQ = Queue.Queue()
    shutterServer = ShutterServer(cmdQ, statusQ)
    shutterServer.setDaemon(True)
    shutterServer.start()
    #cmdQ.put_nowait("apa")
    #cmdQ.put_nowait("UP;1;5")
    #cmdQ.put_nowait("")

    p1 = Pin("GPIO1", 1)
    p2 = Pin("GPIO2", 2)
    s1 = Shutter("Shutter1", p1, p2, shutterStateChange)

    p11 = Pin("GPIO11", 11)
    p12 = Pin("GPIO12", 12)
    s2 = Shutter("Shutter2", p11, p12, shutterStateChange)


    app = tornado.web.Application(
        handlers=[
            (r"/", IndexHandler),
            (r"/ws", WebSocketHandler)
        ], shutter=s1
    )
    httpServer = tornado.httpserver.HTTPServer(app)
    httpServer.listen(options.port)
    print "Listening on port:", options.port
    main_loop = tornado.ioloop.IOLoop.instance()
    sched_periodic = tornado.ioloop.PeriodicCallback(s1.process, 1000, io_loop = main_loop)

    sched_periodic.start()
    main_loop.start()


    
