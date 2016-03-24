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
        #self.write_message("connected")

        print "Connected client: %r" % self.request.remote_ip
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
    ALTERING = 4
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
        elif state == State.ALTERING:
            return "ALTERING"
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
    FORCEUP = 5
    FORCEDOWN = 6

class Shutter:
    _state = State.UNINITED
    _heading = State.UNINITED # Is last command
    _nextCmd = Command.NOCMD
    _cmdDoneAt = getNow()
    _active = False
    _lockedUntil = 0
    _lockedPrio = 100
    _autoReason = ""
    _autoPrio = 100

    def _log(self, msg):
        print "%s %s" % (self._name, msg)

    def getStatus(self):
        return {'state': State.toString(self._state),
                'heading': State.toString(self._heading),
                'busy': self._active,
                'locked': self._lockedUntil,
                'lockedPrio': self._lockedPrio,
                'autoReason': self._autoReason}

    def _setState(self, state):
        self._state = state

    def _setNextCmd(self, cmd, reason):
        self._nextCmd = cmd # Overwrite any waiting command
        self._nextCmdReason = reason

    def _clearNextCmd(self):
        self._nextCmd = Command.NOCMD
        self._nextCmdReason = ""

    def _running(self):
        # Run up or down for 30 seconds
        self._cmdDoneAt = getNow() + 7
        self._active = True

    def _pause(self):
        # Wait 2 seconds before we accept next command so motor doesn't
        # alter direction too fast
        self._cmdDoneAt = getNow() + 2
        self._active = True

    def _runDown(self, reason):
        self._log("DOWN: %r" % reason)
        self._upPin.off()
        self._downPin.on()
        self._setState(State.GOING_DOWN)
        self._running()

    def _runUp(self, reason):
        self._log("UP: %r" % reason)
        self._downPin.off()
        self._upPin.on()
        self._setState(State.GOING_UP)
        self._running()

    def _runStop(self, reason):
        self._log("STOP: %r" % reason)
        self._downPin.off()
        self._upPin.off()
        self._setState(State.STOPPED)
        self._pause()

    def _alterDirection(self, cmd, reason):
        if self._state == State.ALTERING:
            return

        self._log("ALTERING: %r" % reason)
        self._downPin.off()
        self._upPin.off()
        self._setState(State.ALTERING)
        self._pause()
        self._setNextCmd(cmd, reason)

    def _down(self, reason):
        self._heading = State.CLOSED
        if self._state == State.CLOSED or self._state == State.GOING_DOWN:
            return
        elif getNow() <= self._cmdDoneAt:
            self._alterDirection(Command.DOWN, reason)
        else:
            self._runDown(reason)

    def _up(self, reason):
        self._heading = State.OPEN
        if self._state == State.OPEN or self._state == State.GOING_UP:
            return
        elif getNow() <= self._cmdDoneAt:
            self._alterDirection(Command.UP, reason)
        else:
            self._runUp(reason)

    def _stop(self, reason):
        self._heading = State.STOPPED
        self._runStop(reason)

    def __init__(self, name, downPin, upPin):
        self._name = name
        self._downPin = downPin
        self._upPin = upPin

        #Init state, stop, and then down
        #SO if script restarts, we will have a small starting stop pause
        self._alterDirection(Command.DOWN, "Initital DOWN")

    def stop(self):
        self._stop("Manual stop")

    def _lockManual(self):
        offset = 15 * 60
        minTimestamp = getNow() + offset
        if self._lockedUntil < minTimestamp:
            self._lockedUntil = minTimestamp
        if self._lockedPrio > 10:
            self._lockedPrio = 10

    def lockAbsolute(self, timestamp, prio):
        self._log("Lock prio=%d timestamp=%d now=%d" % (prio, timestamp, getNow()))
        self._lockedUntil = timestamp
        self._lockedPrio = prio

    def lockOffset(self, offset, prio):
        self._log("Lock prio=%d offset=%d now=%d" % (prio, offset, getNow()))
        if self._lockedUntil == 0:
            self._lockedUntil = getNow()
        self._lockedUntil += offset
        self._lockedPrio = prio

    def lockUnlock(self):
        self._log("Lock unlock")
        self._lockedUntil = 0

    def manualUp(self):
        self._lockManual()
        self._autoReason = ""
        self._up("Manual up")

    def manualDown(self):
        self._lockManual()
        self._autoReason = ""
        self._down("Manual down")

    def autoUp(self, prio, reason):
        if prio < self._lockedPrio or getNow() > self._lockedUntil:
            self._autoReason = reason
            self._up("Auto Up prio=%d reason=%r" % (prio, reason))

    def autoDown(self, prio, reason):
        if prio < self._lockedPrio or getNow() > self._lockedUntil:
            self._autoReason = reason
            self._down("Auto Down prio=%d reason=%r" % (prio, reason))

    def forceDown(self):
        self._log("Command forceDown")
        self._heading = State.CLOSED
        self._upPin.off()
        self._runDown("Force down")
        self._clearNextCmd()

    def forceUp(self):
        self._log("Command forceUp")
        self._heading = State.OPEN
        self._downPin.off()
        self._runUp("Force up")
        self._clearNextCmd()

    def getHeading(self):
        return self._heading

    def process(self):
        # Called each second

        if self._lockedUntil > 0 and getNow() >= self._lockedUntil:
            self._log("Unlocking!")
            self._lockedUntil = 0
            self._lockedPrio = 100

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
                    self._runUp(self._nextCmdReason)

            elif self._nextCmd == Command.DOWN:
                self._nextCmd = Command.NOCMD
                if self._state != State.CLOSED:
                    self._runDown(self._nextCmdReason)

class ShutterServer(threading.Thread):
    _cmdQ = Queue.Queue()

    _observers = set()
    _observers_lock = threading.Lock()

    _lastStatus = {}

    _rain = False

    _tempSensors = {}
    _nextTempCheck = getNow()

    def sendCommand(self, cmd):
        # Called by other threads!
        self._cmdQ.put_nowait(cmd)

    def subscribeStatus(self, callback):
        # Called by other threads!
        with self._observers_lock:
            self._observers.add(callback)

    def _announceStatus(self, force = False):
        status = {}

        for (name, shutter) in self._shutters.iteritems():
            status[name] = shutter.getStatus()

        status['Rain'] = self._rain

        for (sensor, value) in self._tempSensors.iteritems():
            status[sensor] = value

        if force or status != self._lastStatus:
            #print "Announce: " + str(status)
            with self._observers_lock:
                for cb in self._observers:
                    cb(status.copy()) # Give each observer a copy, if they edit it
            self._lastStatus = status

    def __init__(self):
        threading.Thread.__init__(self)

        _p11 = Pin("GPIO11", 11)
        _p12 = Pin("GPIO12", 12)
        _shutter1 = Shutter("Shutter1", _p11, _p12)

        _p21 = Pin("GPIO21", 21)
        _p22 = Pin("GPIO22", 22)
        _shutter2 = Shutter("Shutter2", _p21, _p22)

        _p31 = Pin("GPIO31", 31)
        _p32 = Pin("GPIO32", 32)
        _shutter3 = Shutter("Shutter3", _p31, _p32)

        _p41 = Pin("GPIO41", 41)
        _p42 = Pin("GPIO42", 42)
        _shutter4 = Shutter("Shutter4", _p41, _p42)

        _p51 = Pin("GPIO51", 51)
        _p52 = Pin("GPIO52", 52)
        _shutter5 = Shutter("Shutter5", _p51, _p52)

        _p61 = Pin("GPIO61", 61)
        _p62 = Pin("GPIO62", 62)
        _shutter6 = Shutter("Shutter6", _p61, _p62)

        self._shutters = {'Shutter1': _shutter1,
                          'Shutter2': _shutter2,
                          'Shutter3': _shutter3,
                          'Shutter4': _shutter4,
                          'Shutter5': _shutter5,
                          'Shutter6': _shutter6,
                          }

    def _getOpenCloseable(self):
        canOpen = []
        canClose = []

        for s in self._shutters.values():
            heading = s.getHeading()
            print heading

            if heading != State.OPEN:
                canOpen.append(s)

            if heading != State.CLOSED:
                canClose.append(s)

        return (canOpen, canClose)

    @staticmethod
    def _getRandom(selection):
        if len(selection) == 0:
            return None
        else:
            return random.choice(selection)

    def _getAnyOpenable(self):
        (selection, _) = self._getOpenCloseable()
        return self._getRandom(selection)

    def _getAnyCloseable(self):
        (_, selection) = self._getOpenCloseable()
        return self._getRandom(selection)

    def _shutterControl(self, msg):
        # Get main params
        try:
            shuttername = msg['shutter']
            cmd = msg['cmd']
        except Exception as e:
            print "ERROR"
            print e
            return

        if shuttername == "ALL":
            shutters = self._shutters.values()

        elif shuttername == "ANY":
            if cmd == "UP":
                shutter = self._getAnyOpenable()
            elif cmd == "DOWN":
                shutter = self._getAnyCloseable()
            else:    
                print "ANY shutter can only be commanded UP or DOWN"
                return

            if shutter is None:
                print "No more shutter to command %r" % cmd
                return

            shutters = [shutter]

        else:
            try:
                shutters = [self._shutters[shuttername]]
            except Exception as e:
                print "No such shutter name: " + shuttername 
                print e
                return

        if cmd == "UP":
            func = lambda x: x.manualUp()

        elif cmd == "DOWN":
            func = lambda x: x.manualDown()

        elif cmd == "STOP":
            func = lambda x: x.stop()

        elif cmd == "FORCEUP":
            func = lambda x: x.forceUp()

        elif cmd == "FORCEDOWN":
            func = lambda x: x.forceDown()

        elif cmd == "LOCK":
            try:
                how = msg['how']
                value = msg['value']
                prio = msg['prio']
            except Exception as e:
                print "ERROR: Missing argument:" + e
                return

            if how == "ABSOLUTE":
                func = lambda x: x.lockAbsolute(value, prio)
            elif how == "OFFSET":
                func = lambda x: x.lockOffset(value, prio)
            else:
                print "ERROR: Unknown how argument:%r" % how
                return

        elif cmd == "LOCK_OFFSET":
            try:
                value = msg['value']
            except Exception as e:
                print "ERROR: Missing 'value' argument"
                return

            func = lambda x: x.lockOffset(value)

        elif cmd == "UNLOCK":
            func = lambda x: x.lockUnlock()

        else:
            print "Unknown command '%s' from client" % cmd
            return

        map(func, shutters)


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
        elif cmd == 'NORAIN':
            self._rain = False
        else:
            print "Unknown rain cmd=%r" % cmd
            return

    def _tempUpdate(self, msg):
        print "Temp: " + str(msg)
        try:
            tempname = msg['temp']
            value = int(msg['value'])

        except Exception as e:
            print "ERROR"
            print e
            return        

        self._tempSensors[tempname] = value

    def _getAvgTemp(self):
        sum = 0
        num = 0
        for t in self._tempSensors.values():
            sum += t
            num += 1
            
        if num > 0:
            return sum/num
        else:
            return 22

    def _processTemp(self):
        if self._rain:
            return # Don't do anything if it is raining

        REFTEMP = 22
        temp = self._getAvgTemp()

        if temp >= REFTEMP + 10:
            for s in self._shutters.values():
                s.autoUp(5, "Very warm")
            return
        elif temp <= REFTEMP - 10:
            for s in self._shutters.values():
                s.autoDown(5, "Very cold")
            return

        if getNow() < self._nextTempCheck:
            return

        if temp >= REFTEMP + 1:
            shutter = self._getAnyOpenable()
            if shutter:
                shutter.autoUp(10, "Warm")
            else:
                print "High temp: Nothing more to open"
            
        elif temp <= REFTEMP - 1:
            shutter = self._getAnyCloseable()
            if shutter:
                shutter.autoDown(10, "Cold")
            else:
                print "Low temp: Nothing more to close"

        self._nextTempCheck = getNow() + 3

    def _processRain(self):
        if self._rain:
            for s in self._shutters.values():
                s.autoDown(2, "Raining")

    def _process(self):
        # Call process() of each shutter once a second
        for shutter in self._shutters.values():
            shutter.process()

        self._processTemp()
        self._processRain()


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
                self._announceStatus(force = True)
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
            self._announceStatus()

if __name__ == "__main__":

    tornado.options.parse_command_line()

    def ioloopCallback(status):
        ioloop = tornado.ioloop.IOLoop.instance()
        ioloop.add_callback(wsSendAll, tornado.escape.json_encode(status))


    def raining(shutterServer):
        wait = 60

        while True:
            time.sleep(wait)
            print "SENDING RAINING!"
            msg = {'what': 'rain', 'cmd': 'RAINING'}
            shutterServer.sendCommand(msg)
            
            time.sleep(wait)
            print "SENDING temp!"
            msg = {'what': 'temp', 'temp': 'TempSensor1', 'value': 25}
            shutterServer.sendCommand(msg)
            
            time.sleep(wait)
            print "SENDING NORAIN!"
            msg = {'what': 'rain', 'cmd': 'NORAIN'}
            shutterServer.sendCommand(msg)
            
            time.sleep(wait)
            print "SENDING temp!"
            msg = {'what': 'temp', 'temp': 'TempSensor1', 'value': 20}
            shutterServer.sendCommand(msg)
            
            time.sleep(wait)
            print "SENDING temp!"
            msg = {'what': 'temp', 'temp': 'TempSensor1', 'value': 24}
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
