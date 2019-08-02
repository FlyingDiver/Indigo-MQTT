#! /usr/bin/env python
# -*- coding: utf-8 -*-
####################

import os
import subprocess
import plistlib
import json
import logging

from mqtt_broker import Broker

kCurDevVersCount = 0        # current version of plugin devices
        
################################################################################
class Plugin(indigo.PluginBase):

    def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs):
        indigo.PluginBase.__init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs)

        pfmt = logging.Formatter('%(asctime)s.%(msecs)03d\t[%(levelname)8s] %(name)20s.%(funcName)-25s%(msg)s', datefmt='%Y-%m-%d %H:%M:%S')
        self.plugin_file_handler.setFormatter(pfmt)

        try:
            self.logLevel = int(self.pluginPrefs[u"logLevel"])
        except:
            self.logLevel = logging.INFO
        self.indigo_log_handler.setLevel(self.logLevel)

    def startup(self):
        self.logger.info(u"Starting MQTT")

        self.brokers = {}            # Dict of Indigo MQTT Brokers, indexed by device.id
        self.triggers = {}
        self.server = None
        
        
        if bool(self.pluginPrefs.get(u"runMQTTServer", False)):
            self.server = subprocess.Popen([os.getcwd()+'/mosquitto', '--daemon', '-p', '1883'])        
     
                    
    def shutdown(self):
        self.logger.info(u"Shutting down MQTT")

        if self.server:
            self.server.kill()

    def runConcurrentThread(self):

        try:
            while True:
            
                for broker in self.brokers.values():
                    broker.loop()

                self.sleep(0.1)

        except self.stopThread:
            pass        



    ########################################
    # Plugin Preference Methods
    ########################################

    def validatePrefsConfigUi(self, valuesDict):
        errorDict = indigo.Dict()

        try:
            self.logLevel = int(valuesDict[u"logLevel"])
        except:
            self.logLevel = logging.INFO
        self.indigo_log_handler.setLevel(self.logLevel)

        if len(errorDict) > 0:
            return (False, valuesDict, errorDict)
        return (True, valuesDict)

    def closedPrefsConfigUi(self, valuesDict, userCancelled):
        if not userCancelled:
            try:
                self.logLevel = int(valuesDict[u"logLevel"])
            except:
                self.logLevel = logging.INFO
            self.indigo_log_handler.setLevel(self.logLevel)
            self.logger.debug(u"MQTT logLevel = " + str(self.logLevel))


    ########################################
    # Device Management Methods
    ########################################
      
    def deviceStartComm(self, device):
        self.logger.debug(u"{}: Starting Device".format(device.name))

        instanceVers = int(device.pluginProps.get('devVersCount', 0))
        if instanceVers == kCurDevVersCount:
            self.logger.threaddebug(u"{}: Device is current version: {}".format(device.name ,instanceVers))
        elif instanceVers < kCurDevVersCount:
            newProps = device.pluginProps
            newProps["devVersCount"] = kCurDevVersCount
            device.replacePluginPropsOnServer(newProps)
            self.logger.debug(u"{}: Updated device version: {} -> {}".format(device.name,  instanceVers, kCurDevVersCount))
        else:
            self.logger.warning(u"{}: Invalid device version: {}".format(device.name, instanceVers))

        device.stateListOrDisplayStateIdChanged()
                
        if device.deviceTypeId == "mqttBroker": 
            self.brokers[device.id] = Broker(device)
            
        else:
            self.logger.warning(u"{}: Invalid device type: {}".format(device.name, device.deviceTypeId))
        
    
    def deviceStopComm(self, device):
        self.logger.debug(u"{}: Stopping Device".format(device.name))
        if device.deviceTypeId == "mqttBroker":
            del self.brokers[device.id]
        
    def didDeviceCommPropertyChange(self, origDev, newDev):
    
        if newDev.deviceTypeId == "mqttBroker":
            if origDev.pluginProps.get('address', None) != newDev.pluginProps.get('address', None):
                return True           
            if origDev.pluginProps.get('port', None) != newDev.pluginProps.get('port', None):
                return True           
            if origDev.pluginProps.get('protocol', None) != newDev.pluginProps.get('protocol', None):
                return True           
            if origDev.pluginProps.get('transport', None) != newDev.pluginProps.get('transport', None):
                return True           
                
        return False

    def getDeviceDisplayStateId(self, device):
        try:
            status_state = device.pluginProps['status_state']
        except:
            status_state = indigo.PluginBase.getDeviceDisplayStateId(self, device)
        return status_state
    
    ########################################
    # Trigger (Event) handling 
    ########################################

    def triggerStartProcessing(self, trigger):
        self.logger.debug("Adding Trigger %s (%d)" % (trigger.name, trigger.id))
        assert trigger.id not in self.triggers
        self.triggers[trigger.id] = trigger

    def triggerStopProcessing(self, trigger):
        self.logger.debug("Removing Trigger %s (%d)" % (trigger.name, trigger.id))
        assert trigger.id in self.triggers
        del self.triggers[trigger.id]

    def triggerCheck(self, device):
        self.logger.debug("triggerCheck: Checking Triggers for Device %s (%d)" % (device.name, device.id))

        for triggerId, trigger in sorted(self.triggers.iteritems()):
            self.logger.debug("\tChecking Trigger %s (%d), %s" % (trigger.name, trigger.id, trigger.pluginTypeId))

            if trigger.pluginProps["brokerID"] == str(device.id):

                if trigger.pluginTypeId == "regexMatch":
                    pattern = trigger.pluginProps["regexPattern"]
                    cPattern = re.compile(pattern)
                    match = cPattern.search(device.states["last_topic"])
                    if match:
                        regexMatch = match.group()
                        self.logger.debug("\t\tExecuting Trigger %s (%d), match: %s" % (trigger.name, trigger.id, regexMatch))
                        indigo.trigger.execute(trigger)
                    else:
                        self.logger.debug("\t\tNo Match for Trigger %s (%d)" % (trigger.name, trigger.id))
                        
                elif trigger.pluginTypeId == "stringMatch":
                    pattern = trigger.pluginProps["stringPattern"]
                    if device.states["last_topic"] == pattern:
                        self.logger.debug("\t\tExecuting Trigger %s (%d)" % (trigger.name, trigger.id))
                        indigo.trigger.execute(trigger)
                    else:
                        self.logger.debug("\t\tNo Match for Trigger %s (%d)" % (trigger.name, trigger.id))

                else:
                    self.logger.debug(
                        "\tUnknown Trigger Type %s (%d), %s" % (trigger.name, trigger.id, trigger.pluginTypeId))

            else:
                self.logger.debug("\t\tSkipping Trigger %s (%s), wrong device: %s" % (trigger.name, trigger.id, device.id))

    ########################################
    # Plugin Actions object callbacks (pluginAction is an Indigo plugin action instance)
    ########################################

    def publishMessageAction(self, pluginAction, brokerDevice, callerWaitingForResult):
        broker = self.brokers[brokerDevice.id]
        topic = indigo.activePlugin.substitute(pluginAction.props["topic"])
        payload = indigo.activePlugin.substitute(pluginAction.props["payload"])
        qos = int(pluginAction.props["qos"])
        retain = bool(pluginAction.props["retain"])
        broker.publish(topic=topic, payload=payload, qos=qos, retain=retain)
        self.logger.debug(u"{}: publishMessageAction {}: {}".format(broker.device.name, topic, payload))

    def publishDeviceAction(self, pluginAction, brokerDevice, callerWaitingForResult):
        broker = self.brokers[brokerDevice.id]
        topic = indigo.activePlugin.substitute(pluginAction.props["topic"])
        qos = int(pluginAction.props["qos"])
        retain = bool(pluginAction.props["retain"])
        pubDevice = indigo.devices[int(pluginAction.props["device"])]
        payload = {}
        payload['name'] = pubDevice.name
        payload['id'] =   pubDevice.id
        payload['states'] = {}
        for key in pubDevice.states:
            payload['states'] [key] = pubDevice.states[key]
        self.logger.debug(u"{}: publishDeviceAction {}: {}".format(broker.device.name, topic, payload))
        broker.publish(topic=topic, payload=json.dumps(payload), qos=qos, retain=retain)


    def addSubscriptionAction(self, pluginAction, brokerDevice, callerWaitingForResult):
        topic = indigo.activePlugin.substitute(pluginAction.props["topic"])
        qos = int(pluginAction.props["qos"])
        self.addSubscription(brokerDevice.id, topic, qos)

    def addSubscriptionMenu(self, valuesDict, typeId):
        deviceId = int(valuesDict["brokerID"])
        topic = indigo.activePlugin.substitute(valuesDict["topic"])
        qos = int(valuesDict["qos"])
        self.addSubscription(deviceId, topic, qos)
        return True

    def addSubscription(self, brokerID, topic, qos):
        broker = self.brokers[brokerID]
        self.logger.debug(u"{}: addSubscription {} ({})".format(broker.device.name, topic, qos))
        broker.subscribe(topic=topic, qos=qos)
        
        updatedPluginProps = broker.device.pluginProps
        if not 'subscriptions' in updatedPluginProps:
           subList = []
        else:
           subList = updatedPluginProps[u'subscriptions']
        if not topic in subList:
            subList.append(topic)
        updatedPluginProps[u'subscriptions'] = subList
        self.logger.debug(u"{}: subscriptions after update :\n{}".format(broker.device.name, updatedPluginProps[u'subscriptions']))
        broker.device.replacePluginPropsOnServer(updatedPluginProps)

    def delSubscriptionAction(self, pluginAction, brokerDevice, callerWaitingForResult):
        topic = indigo.activePlugin.substitute(pluginAction.props["topic"])
        self.delSubscription(brokerDevice.id, topic)

    def delSubscriptionMenu(self, valuesDict, typeId):
        deviceId = int(valuesDict["brokerID"])
        topic = indigo.activePlugin.substitute(valuesDict["topic"])
        self.delSubscription(deviceId, topic)
        return True

    def delSubscription(self, brokerID, topic):
        broker = self.brokers[brokerID]
        broker.unsubscribe(topic=topic)
        self.logger.debug(u"{}: delSubscription {}".format(broker.device.name, topic))
        
        updatedPluginProps = broker.device.pluginProps
        if not 'subscriptions' in updatedPluginProps:
            self.logger.error(u"{}: delSubscription error, subList is empty".format(broker.device.name))
            return
        subList = updatedPluginProps[u'subscriptions']
        if not topic in subList:
            self.logger.debug(u"{}: Topic {} not in subList.".format(broker.device.name, topics))
            return
        subList.remove(topic)
        updatedPluginProps[u'subscriptions'] = subList
        self.logger.debug(u"{}: subscriptions after update :\n{}".format(broker.device.name, updatedPluginProps[u'subscriptions']))
        broker.device.replacePluginPropsOnServer(updatedPluginProps)

    def clearAllSubscriptionsAction(self, pluginAction, brokerDevice, callerWaitingForResult):
        self.clearAllSubscriptions(brokerDevice.id)

    def clearAllSubscriptionsMenu(self, valuesDict, typeId):
        deviceId = int(valuesDict["brokerID"])
        self.clearAllSubscriptions(deviceId)
        return True
    
    def clearAllSubscriptions(self, brokerID):
        broker = self.brokers[brokerID]
        for topic in broker.device.pluginProps[u'subscriptions']:
            self.delSubscription(brokerID, topic)
    
    def printSubscriptionsMenu(self, valuesDict, typeId):
        broker = self.brokers[int(valuesDict["brokerID"])]
        self.logger.info(u"{}: Current topic subscriptions:".format(broker.device.name))
        for topic in broker.device.pluginProps[u'subscriptions']:
            self.logger.info(u"{}:\t\t{}".format(broker.device.name, topic))
        return True
    

    def pickBroker(self, filter=None, valuesDict=None, typeId=0, targetId=0):
        retList = []
        for broker in self.brokers.values():
            retList.append((broker.device.id, broker.device.name))
        retList.sort(key=lambda tup: tup[1])
        return retList

    ########################################################################
    # This method is called to generate a list of plugin identifiers / names
    ########################################################################

    def getProtocolList(self, filter="", valuesDict=None, typeId="", targetId=0):

        retList = []
        indigoInstallPath = indigo.server.getInstallFolderPath()
        pluginFolders =['Plugins', 'Plugins (Disabled)']
        for pluginFolder in pluginFolders:
            tempList = []
            pluginsList = os.listdir(indigoInstallPath + '/' + pluginFolder)
            for plugin in pluginsList:
                # Check for Indigo Plugins and exclude 'system' plugins
                if (plugin.lower().endswith('.indigoplugin')) and (not plugin[0:1] == '.'):
                    # retrieve plugin Info.plist file
                    path = indigoInstallPath + "/" + pluginFolder + "/" + plugin + "/Contents/Info.plist"
                    try:
                        pl = plistlib.readPlist(path)
                    except:
                        self.logger.warning(u"getPluginList: Unable to parse plist, skipping: %s" % (path))
                    else:
                        bundleId = pl["CFBundleIdentifier"]
                        if self.pluginId != bundleId:
                            # Don't include self (i.e. this plugin) in the plugin list
                            displayName = pl["CFBundleDisplayName"]
                            # if disabled plugins folder, append 'Disabled' to name
                            if pluginFolder == 'Plugins (Disabled)':
                                displayName += ' [Disabled]'
                            tempList.append((bundleId, displayName))
            tempList.sort(key=lambda tup: tup[1])
            retList = retList + tempList

        retList.insert(0, ("X-10", "X-10"))
        retList.insert(0, ("Z-Wave", "Z-Wave"))
        retList.insert(0, ("Insteon", "Insteon"))
        return retList

    def getProtocolDevices(self, filter="", valuesDict=None, typeId="", targetId=0):

        retList = []
        deviceProtocol = valuesDict.get("deviceProtocol", None)
        if deviceProtocol == "Insteon":
            for dev in indigo.devices.iter("indigo.insteon"):
                retList.append((dev.id, dev.name))
        
        elif deviceProtocol == "X-10":
            for dev in indigo.devices.iter("indigo.x10"):
                retList.append((dev.id, dev.name))

        elif deviceProtocol == "Z-Wave":
            for dev in indigo.devices.iter("indigo.zwave"):
                retList.append((dev.id, dev.name))

        else:
            for dev in indigo.devices.iter():
                if dev.protocol == indigo.kProtocol.Plugin and dev.pluginId == deviceProtocol:
                    retList.append((dev.id, dev.name))

        retList.sort(key=lambda tup: tup[1])
        return retList


    ########################################
    # Menu Methods
    ########################################

        
    # doesn't do anything, just needed to force other menus to dynamically refresh
    def menuChanged(self, valuesDict, typeId, devId):
        return valuesDict


