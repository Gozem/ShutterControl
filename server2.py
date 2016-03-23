import tornado.httpserver
import tornado.ioloop
import tornado.options
import tornado.web
import tornado.websocket

import time
import Queue
import threading
import random
 
from tornado.options import define, options
define("port", default=9000, help="run on the given port", type=int)
 
class IndexHandler(tornado.web.RequestHandler):
    def get(self):
        self.render('index2.html')


wsClients = set()
def wsSendAll(msg):
    #print "SendAll:" + str(threading.current_thread())
    for c in wsClients:
        c.write_message(msg)

class WebSocketHandler(tornado.websocket.WebSocketHandler):
    def _sendCommand(self, msg):
        sendCmd = self.application.settings.get('sendCmd')
        sendCmd(msg)

    def open(self):
        self.write_message("connected")
        wsClients.add(self)

        data = {'what': "status"}
        self._sendCommand(data)
 
    def on_message(self, msg):
        print 'message received %s' % msg

        cmd = ""
        try:
            data = tornado.escape.json_decode(msg);
            shutter = data['shutter'];
            cmd = data['cmd'];

        except:
            print "ERROR: Can't decode %s" % msg
            return

        print "Got command: %s->%s" % (shutter, cmd)
        data['what'] = "shutter"
        self._sendCommand(data)

        
    def on_close(self):
        print 'connection closed'
        wsClients.discard(self)


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
    _cmdQ = Queue.Queue()

    _observers = set()
    _observers_lock = threading.Lock()

    _status = {}

    _isOpen = set()
    _isClosed = set()

    _rain = False

    def sendCommand(self, cmd):
        # Called by other threads!
        self._cmdQ.put_nowait(cmd)

    def subscribeStatus(self, callback):
        # Called by other threads!
        with self._observers_lock:
            self._observers.add(callback)

    def _announceStatus(self):
        #print "Announce:" + str(threading.current_thread())
        with self._observers_lock:
            for cb in self._observers:
                cb(self._status.copy())

    def _shutterStateChange(self, shutter, name, state, busy):
        msg = name + "_" + State.toString(state) + "_" + str(busy)
        #print "Callback: " + msg

        updated = self._status.copy()
        updated[name] = {'state': State.toString(state),
                         'busy': busy}

        if updated != self._status:
            self._status = updated            
            self._announceStatus()

        self._isOpen.discard(shutter)
        self._isClosed.discard(shutter)
        if state == State.OPEN or state == State.GOING_UP:
            self._isOpen.add(shutter)
        elif state == State.CLOSED or state == State.GOING_DOWN:
            self._isClosed.add(shutter)

        #print self._isOpen
        #print self._isClosed

    def __init__(self):
        threading.Thread.__init__(self)

        _p11 = Pin("GPIO11", 11)
        _p12 = Pin("GPIO12", 12)
        _shutter1 = Shutter("Shutter1", _p11, _p12, self._shutterStateChange)

        _p21 = Pin("GPIO21", 21)
        _p22 = Pin("GPIO22", 22)
        _shutter2 = Shutter("Shutter2", _p21, _p22, self._shutterStateChange)

        _p31 = Pin("GPIO31", 31)
        _p32 = Pin("GPIO32", 32)
        _shutter3 = Shutter("Shutter3", _p31, _p32, self._shutterStateChange)

        _p41 = Pin("GPIO41", 41)
        _p42 = Pin("GPIO42", 42)
        _shutter4 = Shutter("Shutter4", _p41, _p42, self._shutterStateChange)

        _p51 = Pin("GPIO51", 51)
        _p52 = Pin("GPIO52", 52)
        _shutter5 = Shutter("Shutter5", _p51, _p52, self._shutterStateChange)

        _p61 = Pin("GPIO61", 61)
        _p62 = Pin("GPIO62", 62)
        _shutter6 = Shutter("Shutter6", _p61, _p62, self._shutterStateChange)

        self._shutters = {'Shutter1': _shutter1,
                          'Shutter2': _shutter2,
                          'Shutter3': _shutter3,
                          'Shutter4': _shutter4,
                          'Shutter5': _shutter5,
                          'Shutter6': _shutter6,
                          }

    def _shutterControl(self, msg):
        try:
            shuttername = msg['shutter']
            cmd = msg['cmd']

            if shuttername == "ALL":
                shutters = self._shutters.values()
            elif shuttername == "ANY":
                if cmd == "UP":
                    if len(self._isClosed) > 0:
                        shutters = random.sample(self._isClosed, 1)
                    else:
                        return
                elif cmd == "DOWN":
                    if len(self._isOpen) > 0:
                        shutters = random.sample(self._isOpen, 1)
                    else:
                        return
                else:
                    return # Can't exec STOP, or FORCEUP/DOWN on ANY random shutter
            else:
                print "elsebr"
                shutters = [self._shutters[shuttername]]

        except Exception as e:
            print "ERROR"
            print e
            return

        print shutters

        if cmd == "UP":
            for s in shutters:
                s.up()
        elif cmd == "DOWN":
            for s in shutters:
                s.down()
        elif cmd == "STOP":
            for s in shutters:
                s.stop()
        elif cmd == "FORCEUP":
            for s in shutters:
                s.forceUp()
        elif cmd == "FORCEDOWN":
            for s in shutters:
                s.forceDown()
        else:
            print "Unknown command '%s' from client" % cmd

    def _rainUpdate(self, msg):
        print "Rain: " + str(msg)
        try:
            cmd = msg['cmd']

        except Exception as e:
            print "ERROR"
            print e
            return        

        if cmd == 'RAINING':
            self._rain = True
            self._status['Rain'] = True
            for s in self._shutters.values():
                s.down()
        elif cmd == 'NORAIN':
            self._status['Rain'] = False
            self._rain = False

        self._announceStatus()

    def _process(self):
        # Call process() of each shutter once a second
        for (_, shutter) in self._shutters.iteritems():
            shutter.process()

    def _handleMsg(self):
            try:
                msg = self._cmdQ.get(True, 1) # Wait for a command for 1 sec
                print "MSG: " + repr(msg)

                if msg['what'] == 'shutter':
                    self._shutterControl(msg)
                elif msg['what'] == 'temp':
                    self._tempUpdate(msg)
                elif msg['what'] == 'rain':
                    self._rainUpdate(msg)
                elif msg['what'] == 'status':
                    self._announceStatus()
                else:
                    print "ERROR: Unknown msg['what']: %s" % msg['what']

                self._cmdQ.task_done()

            except Queue.Empty:
                pass

    def run(self):
        print "ShutterServer running!"
        while True:
            self._handleMsg()
            self._process()
 
if __name__ == "__main__":

    tornado.options.parse_command_line()

    def ioloopCallback(status):
        ioloop = tornado.ioloop.IOLoop.instance()
        ioloop.add_callback(wsSendAll, tornado.escape.json_encode(status))


    def raining(shutterServer):
        time.sleep(10)
        print "SENDING RAINING!"
        msg = {'what': 'rain', 'cmd': 'RAINING'}
        shutterServer.sendCommand(msg)
    

    print "starting shutterserver"



    shutterServer = ShutterServer()
    shutterServer.setDaemon(True)
    shutterServer.subscribeStatus(ioloopCallback)
    shutterServer.start()

    t = threading.Thread(target=raining, args=(shutterServer,))
    t.setDaemon(True)
    t.start()

    app = tornado.web.Application(
        handlers=[
            (r"/", IndexHandler),
            (r"/ws", WebSocketHandler)
        ], sendCmd=shutterServer.sendCommand
    )
    httpServer = tornado.httpserver.HTTPServer(app)
    httpServer.listen(options.port)
    print "Listening on port:", options.port
    main_loop = tornado.ioloop.IOLoop.instance()
    #sched_periodic = tornado.ioloop.PeriodicCallback(s1.process, 1000, io_loop = main_loop)
    #sched_periodic.start()
    main_loop.start()
