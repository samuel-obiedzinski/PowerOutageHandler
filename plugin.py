# -*- coding: utf-8 -*-
from Plugins.Plugin import PluginDescriptor
from Components.ConfigList import ConfigListScreen
from Components.config import config, getConfigListEntry, ConfigSubsection, ConfigEnableDisable, ConfigInteger, ConfigSelection
from Components.Sources.StaticText import StaticText
from Components.ActionMap import ActionMap
from enigma import eTimer, eActionMap, eConsoleAppContainer, getDesktop
from Screens.Screen import Screen

import os
import stat

config.plugins.PowerOutageHandler = ConfigSubsection()
config.plugins.PowerOutageHandler.Delay = ConfigInteger(60, (5, 300))
config.plugins.PowerOutageHandler.Mode = ConfigSelection(default = "standby", choices = [("standby", "standby"),("standby_notify", "standby notify"),("deepstandby", "deep standby")]) 

STATE_FILE = "/etc/enigma2/poh_state.txt"
STATE_STANDBY = 0
STATE_NORMAL = 1

def IsInStandby():
    from Screens.Standby import inStandby
    return inStandby != None

def Print(txt):
    with open("/tmp/PowerOutageHandler.txt", "a+") as f:
        f.write("%s" % txt)
        f.write('\n')
    print('PowerOutageHandler: %s' % txt)

def GetState():
    try:
        with open(STATE_FILE, "r") as f:
            data = f.read().strip()
        if data == "standby":
            return STATE_STANDBY
        elif data == "normal":
            return STATE_NORMAL
        Print('GetState: unknown state "%s"' % data)
    except Exception as e:
        Print('GetState %s' % e)
    return STATE_NORMAL

def SetState(state):
    if state != GetState():
        try:
            if state == STATE_STANDBY:
                data = b'standby'
            elif state == STATE_NORMAL:
                data = b'normal'
            else:
                Print('SetState: unknown state "%d"' % state)
                data = b'normal'

            # If os.O_FSYNC set, each write call will make sure the data
            # is reliably stored on disk before returning.
            O_FSYNC = 0
            try:
                O_FSYNC = os.O_FSYNC
            except Exception:
                try:
                    O_FSYNC = os.O_SYNC
                except Exception as e:
                    Print('O_FSYNC %s' % e)
                    O_FSYNC = 0
            fd = os.open(STATE_FILE, os.O_WRONLY | os.O_TRUNC | O_FSYNC | os.O_CREAT)
            os.write(fd, data)
            #if O_FSYNC == 0:
            try:
                os.fdatasync(fd)
            except Exception:
                try:
                    os.fsync(fd)
                except Exception as e:
                    Print('os.fsync %s' % e)
            os.close(fd)

        except Exception as e:
            Print('SetState %s' % e)

def LeaveStandby():
    Print('LeaveStandby called')
    SetState(STATE_NORMAL)

def StandbyCountChanged(configElement=None):
    Print('StandbyCountChanged called')
    try:
        SetState(STATE_STANDBY)
        from Screens.Standby import inStandby
        if LeaveStandby not in inStandby.onClose:
            inStandby.onClose.append(LeaveStandby)
    except Exception as e:
        Print('StandbyCountChanged: %s' % e)

def DeepStandbyChanged(configElement=None):
    Print('DeepStandbyChanged called')
    try:
        if configElement.value:
            SetState(STATE_STANDBY)
    except Exception as e:
        Print('DeepStandbyChanged: %s' % e)

class eConnectCallbackObj:
    def __init__(self, obj=None, connectHandler=None):
        self.connectHandler = connectHandler
        self.obj = obj

    def __del__(self):
        try:
            if 'connect' not in dir(self.obj):
                if 'get' in dir(self.obj):
                    self.obj.get().remove(self.connectHandler)
                else:
                    self.obj.remove(self.connectHandler)
            else:
                del self.connectHandler
        except Exception as e:
            Print(e)
        self.connectHandler = None
        self.obj = None

def eConnectCallback(obj, callbackFun, withExcept=False):
    try:
        if 'connect' in dir(obj):
            return eConnectCallbackObj(obj, obj.connect(callbackFun))
        else:
            if 'get' in dir(obj):
                obj.get().append(callbackFun)
            else:
                obj.append(callbackFun)
            return eConnectCallbackObj(obj, callbackFun)
    except Exception as e:
        Print(e)
    return eConnectCallbackObj()

class PONotification(Screen):

    def getSkin(self):
        try:
            width = int( getDesktop(0).size().width())
        except Exception as e:
            width = 1280
            Print(e)

        if width >= 1920:
            logo = "logohd.png"
            imgWidth = 150
            imgHeight = 60
        else:
            logo = "logo.png"
            imgWidth = 100
            imgHeight = 40

        pluginPath = os.path.dirname(os.path.abspath(os.path.join(__file__)))
        logo = os.path.join(pluginPath, logo)

        x = (width - imgWidth) / 2
        skin = """<screen position="%d,5" zPosition="11" size="%d,%d" backgroundColor="transparent" title="PowerOutage" flags="wfNoBorder">
                <ePixmap position="0,0" size="%d,%d" pixmap="%s" alphatest="on" />
            </screen>""" % (x, imgWidth, imgHeight, imgWidth, imgHeight, logo)
        return skin

    def __init__(self, session):
        Screen.__init__(self, session)
        self.skin = self.getSkin()

class PowerOutageHandlerSetup(Screen, ConfigListScreen):

    def __init__(self, m_session):
        Screen.__init__(self, m_session)
        self.title = _("PowerOutageHandler Setup")
        self.skinName = "Setup"

        self["key_red"] = StaticText("")
        self["key_green"] = StaticText("")

        self["actions"] = ActionMap(["SetupActions"],
        {
            "cancel": self.close,
            "ok": self.close,
        }, -2)

        self.list = []
        ConfigListScreen.__init__(self, self.list, m_session, self.Change)
        self.BuildList()

    def BuildList(self):
        self.list = []

        self.list.append(getConfigListEntry(_("Mode"), config.plugins.PowerOutageHandler.Mode))
        self.list.append(getConfigListEntry(_("Delay in seconds"), config.plugins.PowerOutageHandler.Delay))

        self["config"].list = self.list
        self["config"].l.setList(self.list)
        self["config"].l.setSeperation(300)

    def Change(self):
        self.KeySave()
        self.BuildList()

    def KeySave(self):
        for x in self["config"].list:
            x[1].save()

class PowerOutageHandlerControl:
    POH_WAKEUP_REASON_PATH = "/tmp/poh_wakeup_reason"
    def __init__(self, m_session):
        self.m_session = m_session
        self.m_enabled = True
        self.m_dialog = None
        self.m_autoTimer = None
        self.m_blinkCnt = 0
        self.m_actionBind = False
        try: self.m_fristStart = not os.path.isfile(self.POH_WAKEUP_REASON_PATH)
        except Exception: self.m_fristStart = True

        self.m_console = None

        pluginPath = os.path.dirname(os.path.abspath(os.path.join(__file__)))
        self.m_binary = os.path.join(pluginPath, 'WakeupReason')
        try:
            if not os.access(self.m_binary, os.X_OK):
                os.chmod(self.m_binary, stat.S_IXUSR|stat.S_IXGRP)
        except Exception as e:
            Print(e)

        # last state was normal
        if STATE_NORMAL == GetState():
            self.disable()

        if self.isEnabled():
            eActionMap.getInstance().bindAction('', -0x7FFFFFFF, self.keyPressed)
            self.m_actionBind = True

        if self.m_fristStart:
            # we need to call this after each coldboot, to clear wakeup reason after read 
            # otherwise it will be preserved in case of software reboot on HiSilicon devices
            self.m_console = eConsoleAppContainer()
            self.m_console_stdoutAvail_conn = eConnectCallback(self.m_console.stdoutAvail, self.dataAvail)
            self.m_console_stderrAvail_conn = eConnectCallback(self.m_console.stderrAvail, self.stderrAvail)
            self.m_console_appClosed_conn = eConnectCallback(self.m_console.appClosed, self.cmdFinished)
            self.m_stdoutData = b""
            self.m_stderrData = b""
            self.m_console.execute(self.m_binary)
        elif STATE_STANDBY == GetState():
            # user restart GUI? -> restore last state
            self.startTimer()

        # we will monitor and save state to restore it after power failure
        config.misc.standbyCounter.addNotifier(StandbyCountChanged, initial_call=False)
        config.misc.DeepStandby.addNotifier(DeepStandbyChanged, initial_call=False)

    def dataAvail(self, data):
        if data:
            self.m_stdoutData += data

    def stderrAvail(self, data):
        if data:
            self.m_stderrData += data

    def cmdFinished(self, code):
        self.m_console_appClosed_conn = None
        self.m_console_stdoutAvail_conn = None
        self.m_console = None

        try:
            with open(self.POH_WAKEUP_REASON_PATH, "wb") as f:
                f.write(self.m_stdoutData)
        except Exception as e:
            Print(e)

        if b'(master power)' in (self.m_stdoutData + self.m_stderrData):
            self.m_console = eConsoleAppContainer()
            self.m_console_appClosed_conn = eConnectCallback(self.m_console.appClosed, self.startTimer)
            self.m_console.execute(self.m_binary + " clear")
        else:
            self.disable()

    def startTimer(self, code=0):
        self.m_console_appClosed_conn = None
        self.m_console_stdoutAvail_conn = None
        self.m_console = None
        if self.isEnabled():
            Print('Start delay timer: %d seconds' % config.plugins.PowerOutageHandler.Delay.getValue())
            self.m_dialog = self.m_session.instantiateDialog(PONotification)
            self.m_dialog.show()
            self.m_autoTimer = eTimer()
            self.m_autoTimer_conn = eConnectCallback(self.m_autoTimer.timeout, self.blink)
            self.m_autoTimer.start(1000)

    def disable(self, goingToStandby=None):
        state = STATE_STANDBY if IsInStandby() else STATE_NORMAL
        if not goingToStandby:
            SetState(state)

        if self.m_enabled:
            Print('Disabled')
            self.m_enabled = False
            try:
                if self.m_autoTimer:
                    self.m_autoTimer.stop()
                self.m_autoTimer_conn = None
                self.m_autoTimer = None
                if self.m_actionBind:
                    eActionMap.getInstance().unbindAction('', self.keyPressed)
                    self.m_actionBind = False
            except Exception as e:
                Print(e)
        try:
            if self.m_dialog:
                self.m_dialog.hide()
                self.m_dialog.close()
                self.m_dialog = None
        except Exception as e:
            Print(e)

    def isEnabled(self):
        if IsInStandby():
            self.disable()
        return self.m_enabled

    def blink(self):
        self.m_blinkCnt += 1
        if self.m_blinkCnt < config.plugins.PowerOutageHandler.Delay.getValue():
            if self.m_blinkCnt % 2 == 0:
                self.m_dialog.show()
            else:
                self.m_dialog.hide()
        else:
            self.m_autoTimer.stop()
            self.m_autoTimer_conn = None
            self.m_autoTimer = None

            Print('Go to standby!')

            goingToStandby = True
            mode = config.plugins.PowerOutageHandler.Mode.value
            if mode == 'standby':
                from Screens.Standby import Standby
                self.m_session.open(Standby)
            elif mode == 'standby_notify':
                from Screens.Standby import Standby
                from Tools import Notifications
                Notifications.AddNotification(Standby)
            elif mode == 'deepstandby':
                from Screens.Standby import TryQuitMainloop, QUIT_SHUTDOWN
                self.m_session.open(TryQuitMainloop, QUIT_SHUTDOWN)
            else:
                Print('Wrong mode value "%s"' % mode)
                goingToStandby = False
            self.disable(goingToStandby)

    def keyPressed(self, key, flag):
        Print('keyPressed')
        self.disable()

POHInstance = None

def autostart(session, **kwargs):
    global POHInstance
    if POHInstance is None:
        POHInstance = PowerOutageHandlerControl(session)

def main(session, **kwargs):
    session.open(PowerOutageHandlerSetup)

def Plugins(path, **kwargs):
    logo = "logo.png"
    try:
        if getDesktop(0).size().width() >= 1920:
            logo = "logohd.png"
    except Exception as e:
        Print(e)

    return [PluginDescriptor(name="PowerOutageHandler", description = "PowerOutageHandler setup", where = PluginDescriptor.WHERE_PLUGINMENU, fnc = main, needsRestart = False, icon = logo),
            PluginDescriptor(name="PowerOutageHandler", description = "PowerOutageHandler v0.2", where = PluginDescriptor.WHERE_SESSIONSTART, fnc = autostart, needsRestart = False, weight = -1)]
