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

        self.logLevel = int(self.pluginPrefs.get(u"logLevel", logging.INFO))
        self.indigo_log_handler.setLevel(self.logLevel)

    def startup(self):
        self.logger.info(u"Starting MQTT")

        self.brokers = {}            # Dict of Indigo MQTT Brokers, indexed by device.id
        self.triggers = {}
        self.server = None
        
        if bool(self.pluginPrefs.get(u"runMQTTServer", False)):
            self.server = subprocess.Popen([os.getcwd()+'/mosquitto', '-p', '1883'])
            self.sleep(3.0)

     
                    
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
            if origDev.pluginProps.get('username', None) != newDev.pluginProps.get('username', None):
                return True           
            if origDev.pluginProps.get('password', None) != newDev.pluginProps.get('password', None):
                return True           
            if origDev.pluginProps.get('useTLS', None) != newDev.pluginProps.get('useTLS', None):
                return True           

            # a bit of a hack to make sure name changes get pushed down immediately                
            self.brokers[newDev.id].refreshFromServer()
                
        return False
    
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
    # This is the method that's called by the Add Topic button in the device in the Broker device config UI.
    ########################################
    
    def addTopic(self, valuesDict, typeId, deviceId):

        topic = valuesDict["newTopic"]
        qos = valuesDict["qos"]
        s = "{}:{}".format(qos, topic)
        
        topicList = list()
        if 'subscriptions' in valuesDict:
            for t in valuesDict['subscriptions']:
                topicList.append(t) 
        if s not in topicList:
            topicList.append(s)
            valuesDict['updateSubscriptions'] = True
        valuesDict['subscriptions'] = topicList
        
        return valuesDict

    ########################################
    # This is the method that's called by the Delete Subscriptions button in the Broker device config UI.
    ########################################
    
    def deleteSubscriptions(self, valuesDict, typeId, deviceId):
        topicList = list()
        if 'subscriptions' in valuesDict:
            for t in valuesDict['subscriptions']:
                topicList.append(t) 
        for t in valuesDict['items']:
            if t in topicList:
                topicList.remove(t)
                valuesDict['updateSubscriptions'] = True
        valuesDict['subscriptions'] = topicList
        return valuesDict

    ########################################
    # This is the method that's called to build the topic subscription list in the Broker device config UI.
    ########################################
    
    def subscribedList(self, filter, valuesDict, typeId, deviceId):
        returnList = list()
        if 'subscriptions' in valuesDict:
            for topic in valuesDict['subscriptions']:
                returnList.append(topic)
        return returnList
        

    ########################################
    # This is the method that's called by the Add Device button in the Broker device config UI.
    ########################################
    
    def addDevice(self, valuesDict, typeId, deviceId):
        d = valuesDict["deviceSelected"]
        deviceList = list()
        if 'broadcastDevs' in valuesDict:
            for t in valuesDict['broadcastDevs']:
                deviceList.append(t) 
        if d not in deviceList:
            deviceList.append(d)
        valuesDict['broadcastDevs'] = deviceList
        return valuesDict

    ########################################
    # This is the method that's called by the Delete Devices button in the Broker device config UI.
    ########################################
    
    def deleteDevices(self, valuesDict, typeId, deviceId):
        deviceList = list()
        if 'broadcastDevs' in valuesDict:
            for t in valuesDict['broadcastDevs']:
                deviceList.append(t) 
        for t in valuesDict['devList']:
            if t in deviceList:
                deviceList.remove(t)
        valuesDict['broadcastDevs'] = deviceList
        return valuesDict

    ########################################
    # This is the method that's called to build the broadcast device list in the Broker device config UI.
    ########################################
    
    def broadcastList(self, filter, valuesDict, typeId, deviceId):
        returnList = list()
        if 'broadcastDevs' in valuesDict:
            for d in valuesDict['broadcastDevs']:
                returnList.append((d, indigo.devices[int(d)].name))
        return returnList
        
    ########################################

    def validateDeviceConfigUi(self, valuesDict, typeId, deviceId):
        if valuesDict.get('updateSubscriptions', False):
            # sync subscriptions to Broker
            if 'subscriptions' in valuesDict:
                broker = self.brokers[deviceId]
                for s in valuesDict['subscriptions']:
                    qos = int(s[0:1])
                    topic = s[2:]
                    broker.subscribe(topic=topic, qos=qos)
        return (True, valuesDict)


    ########################################
    # Menu Methods
    ########################################
            
    def printSubscriptionsMenu(self, valuesDict, typeId):
        device = indigo.devices[int(valuesDict["brokerID"])]
        self.logger.info(u"{}: Current topic subscriptions:".format(device.name))
        for s in device.pluginProps[u'subscriptions']:
            qos = int(s[0:1])
            topic = s[2:]
            self.logger.info(u"{}: {} ({})".format(device.name, topic, qos))
        return True
    
    # doesn't do anything, just needed to force other menus to dynamically refresh
    def menuChanged(self, valuesDict, typeId, devId):
        return valuesDict


    ########################################
    # Plugin Actions object callbacks (pluginAction is an Indigo plugin action instance)
    ########################################

    def publishMessageAction(self, pluginAction, brokerDevice, callerWaitingForResult):
        broker = self.brokers[brokerDevice.id]
        topic = indigo.activePlugin.substitute(pluginAction.props["topic"])
        payload = indigo.activePlugin.substitute(pluginAction.props["payload"])
        qos = int(pluginAction.props["qos"])
        retain = bool(pluginAction.props["retain"])
        self.logger.debug(u"{}: publishMessageAction {}: {}, {}, {}".format(brokerDevice.name, topic, payload, qos, retain))
        broker.publish(topic=topic, payload=payload, qos=qos, retain=retain)

    def publishDeviceAction(self, pluginAction, brokerDevice, callerWaitingForResult):
        broker = self.brokers[brokerDevice.id]
        topic = indigo.activePlugin.substitute(pluginAction.props["topic"])
        qos = int(pluginAction.props["qos"])
        retain = bool(pluginAction.props["retain"])
        pubDevice = indigo.devices[int(pluginAction.props["device"])]
        payload = {}
        payload['address'] = pubDevice.address
        payload['name'] = pubDevice.name
        payload['model'] = pubDevice.model
        payload['id'] =   pubDevice.id
        payload['states'] = {}
        for key in pubDevice.states:
            payload['states'] [key] = pubDevice.states[key]
        payload['pluginProps'] = {}
        for key in pubDevice.pluginProps:
            payload['states'] [key] = pubDevice.pluginProps[key]
        self.logger.debug(u"{}: publishDeviceAction {}: {}, {}, {}".format(brokerDevice.name, topic, payload, qos, retain))
        broker.publish(topic=topic, payload=json.dumps(payload), qos=qos, retain=retain)

    def addSubscriptionAction(self, pluginAction, brokerDevice, callerWaitingForResult):
        topic = indigo.activePlugin.substitute(pluginAction.props["topic"])
        qos = int(pluginAction.props["qos"])
        self.addSubscription(brokerDevice.id, topic, qos)

    def delSubscriptionAction(self, pluginAction, brokerDevice, callerWaitingForResult):
        topic = indigo.activePlugin.substitute(pluginAction.props["topic"])
        self.delSubscription(brokerDevice.id, topic)

    def clearAllSubscriptionsAction(self, pluginAction, brokerDevice, callerWaitingForResult):
        self.clearAllSubscriptions(brokerDevice.id)


    def pickBroker(self, filter=None, valuesDict=None, typeId=0, targetId=0):
        retList = []
        for brokerID in self.brokers:
            device = indigo.devices[int(brokerID)]
            retList.append((device.id, device.name))
        retList.sort(key=lambda tup: tup[1])
        return retList

    ########################################
    # Utility routines used for Actions and Menu commands
    ########################################

    def addSubscription(self, brokerID, topic, qos):
        broker = self.brokers[brokerID]
        device = indigo.devices[int(brokerID)]
        broker.subscribe(topic=topic, qos=qos)
        self.logger.debug(u"{}: addSubscription {} ({})".format(device.name, topic, qos))
        
        updatedPluginProps = device.pluginProps
        if not 'subscriptions' in updatedPluginProps:
           subList = []
        else:
           subList = updatedPluginProps[u'subscriptions']
        if not topic in subList:
            subList.append(topic)
        updatedPluginProps[u'subscriptions'] = subList
        self.logger.debug(u"{}: subscriptions after update :\n{}".format(device.name, updatedPluginProps[u'subscriptions']))
        device.replacePluginPropsOnServer(updatedPluginProps)

    def delSubscription(self, brokerID, topic):
        broker = self.brokers[brokerID]
        device = indigo.devices[int(brokerID)]
        broker.unsubscribe(topic=topic)
        self.logger.debug(u"{}: delSubscription {}".format(device.name, topic))
        
        updatedPluginProps = device.pluginProps
        if not 'subscriptions' in updatedPluginProps:
            self.logger.error(u"{}: delSubscription error, subList is empty".format(device.name))
            return
        subList = updatedPluginProps[u'subscriptions']
        if not topic in subList:
            self.logger.debug(u"{}: Topic {} not in subList.".format(device.name, topics))
            return
        subList.remove(topic)
        updatedPluginProps[u'subscriptions'] = subList
        self.logger.debug(u"{}: subscriptions after update :\n{}".format(device.name, updatedPluginProps[u'subscriptions']))
        device.replacePluginPropsOnServer(updatedPluginProps)

    def clearAllSubscriptions(self, brokerID):
        broker = self.brokers[brokerID]
        device = indigo.devices[int(brokerID)]
        for topic in device.pluginProps[u'subscriptions']:
            self.delSubscription(brokerID, topic)
    

    ########################################################################
    # This method is called to generate a list of plugin identifiers / names
    ########################################################################

    def getProtocolList(self, filter="", valuesDict=None, typeId="", targetId=0):

        retList = []
        indigoInstallPath = indigo.server.getInstallFolderPath()
#        pluginFolders =['Plugins', 'Plugins (Disabled)']
        pluginFolders =['Plugins']
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


