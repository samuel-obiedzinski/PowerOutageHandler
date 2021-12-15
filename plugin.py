# -*- coding: utf-8 -*-
from Plugins.Plugin import PluginDescriptor
from Components.ConfigList import ConfigListScreen
from Components.config import config, getConfigListEntry, ConfigSubsection, ConfigEnableDisable, ConfigInteger
from Components.Sources.StaticText import StaticText
from Components.ActionMap import ActionMap
from enigma import eTimer, eActionMap, eConsoleAppContainer, getDesktop
from Screens.Standby import Standby, inStandby
from Screens.Screen import Screen
from Tools import Notifications

import os
import stat

config.plugins.PowerOutageHandler = ConfigSubsection()
config.plugins.PowerOutageHandler.Enable = ConfigEnableDisable(default=True)
config.plugins.PowerOutageHandler.Delay = ConfigInteger(30, (5, 300))

def Print(txt):
    print('PowerOutageHandler: %s' % txt)

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

        self.list.append(getConfigListEntry(_("Auto Standby after Power Outage"), config.plugins.PowerOutageHandler.Enable))
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

    def __init__(self, m_session):
        self.m_session = m_session
        self.m_enabled = config.plugins.PowerOutageHandler.Enable.getValue()
        self.m_dialog = None
        self.m_autoTimer = None
        self.m_blinkCnt = 0

        self.m_stdoutData = b""
        self.m_stderrData = b""
        self.m_console = eConsoleAppContainer()
        self.m_console_stdoutAvail_conn = eConnectCallback(self.m_console.stdoutAvail, self.dataAvail)
        self.m_console_stderrAvail_conn = eConnectCallback(self.m_console.stderrAvail, self.stderrAvail)
        self.m_console_appClosed_conn = eConnectCallback(self.m_console.appClosed, self.cmdFinished)

        pluginPath = os.path.dirname(os.path.abspath(os.path.join(__file__)))
        self.m_binary = os.path.join(pluginPath, 'WakeupReason')
        try:
            if not os.access(self.m_binary, os.X_OK):
                os.chmod(self.m_binary, stat.S_IXUSR|stat.S_IXGRP)
        except Exception as e:
            Print(e)
        self.m_console.execute(self.m_binary)

        if self.isEnabled():
            eActionMap.getInstance().bindAction('', -0x7FFFFFFF, self.keyPressed)

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

        if b'(master power)' in (self.m_stdoutData + self.m_stderrData):
            self.m_console = eConsoleAppContainer()
            self.m_console_appClosed_conn = eConnectCallback(self.m_console.appClosed, self.startTimer)
            self.m_console.execute(self.m_binary + " clear")
        else:
            self.disable()

    def startTimer(self, code):
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

    def disable(self):
        if self.m_enabled:
            Print('Disabled')
            self.m_enabled = False
            try:
                if self.m_autoTimer:
                    self.m_autoTimer.stop()
                self.m_autoTimer_conn = None
                self.m_autoTimer = None
                eActionMap.getInstance().unbindAction('', self.keyPressed)
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
        if inStandby:
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

            Notifications.AddNotification(Standby)
            self.disable()

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
            PluginDescriptor(name="PowerOutageHandler", description = "PowerOutageHandler", where = PluginDescriptor.WHERE_SESSIONSTART, fnc = autostart, needsRestart = False, weight = -1)]
