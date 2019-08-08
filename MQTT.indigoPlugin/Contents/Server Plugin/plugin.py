#! /usr/bin/env python
# -*- coding: utf-8 -*-
####################

import os
import plistlib
import json
import logging
import pystache
import re

from subprocess import PIPE, Popen
from threading  import Thread
from Queue import Queue, Empty

from mqtt_broker import Broker

kCurDevVersCount = 0        # current version of plugin devices
    
# normally used for file system paths, but will work for slash separated topics

def splitall(path):
    allparts = []
    while 1:
        parts = os.path.split(path)
        if parts[0] == path:  # sentinel for absolute paths
            allparts.insert(0, parts[0])
            break
        elif parts[1] == path: # sentinel for relative paths
            allparts.insert(0, parts[1])
            break
        else:
            path = parts[0]
            allparts.insert(0, parts[1])
    return allparts 

def makeDevForJSON(device):
    dev_data = {}
    dev_data['name'] = device.name
    dev_data['deviceId'] = device.id
    dev_data['model'] = device.model
    dev_data['address'] = device.address
    dev_data['states'] = []
    for key, value in device.states.iteritems():
        dev_data['states'].append({'name': key, 'value': value})
    return dev_data

def makeVarForJSON(variable):
    var_data = {}
    var_data['name'] = variable.name
    var_data['variableId'] = variable.id
    var_data['value'] = variable.value
    return var_data
    
def enqueue_output(out, queue):
    for line in iter(out.readline, b''):
        queue.put(line)
    out.close()
 
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
        self.queueDict = {}
        self.server = None

        indigo.devices.subscribeToChanges()
        indigo.variables.subscribeToChanges()
        
        if bool(self.pluginPrefs.get(u"runMQTTServer", False)):
            self.logger.info(u"Starting mosquitto MQTT server")
            args = [os.getcwd()+'/mosquitto', '-p', '1883']
            if bool(self.pluginPrefs.get(u"verboseMQTTServer", False)):
                args.append('-v')
            self.server = Popen(args, stderr=PIPE, bufsize=1)
            self.q_stderr = Queue()
            t = Thread(target=enqueue_output, args=(self.server.stderr, self.q_stderr))
            t.daemon = True
            t.start()

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
                if self.server:
                    try:  
                        line = self.q_stderr.get_nowait()
                    except Empty:
                        pass
                    else: 
                        self.logger.debug(u"(mosquitto) {}".format(line.rstrip()))
                
                self.sleep(0.1)
        except self.stopThread:
            pass        
            

    def deviceUpdated(self, origDevice, newDevice):
        indigo.PluginBase.deviceUpdated(self, origDevice, newDevice)
        for brokerID in self.brokers:
            brokerDevice = indigo.devices[int(brokerID)]
            broker = self.brokers[brokerDevice.id]
            devList = brokerDevice.pluginProps.get(u'published_devices', None)
            if devList and unicode(newDevice.id) in devList:
                dev_data = makeDevForJSON(newDevice)
#                self.logger.debug(u"deviceUpdated, dev_data = {}".format(dev_data))
                topic_template =  brokerDevice.pluginProps.get("device_template_topic", None)
                if not topic_template:
                    return
                topic = pystache.render(topic_template, dev_data)
                payload_template = brokerDevice.pluginProps.get("device_template_payload", None)
                if not payload_template:
                    return
                payload = pystache.render(payload_template, dev_data)
                payload = " ".join(re.split("\s+", payload, flags=re.UNICODE)).replace(", }", " }")

                qos = int(brokerDevice.pluginProps.get("device_template_qos", 1))
                retain = bool(brokerDevice.pluginProps.get("device_template_retain", False))
#                self.logger.debug(u"deviceUpdated, topic = {}, payload = {}".format(topic, payload))
                broker.publish(topic=topic, payload=payload, qos=qos, retain=retain)

    def variableUpdated(self, origVariable, newVariable):
        indigo.PluginBase.variableUpdated(self, origVariable, newVariable)
        for brokerID in self.brokers:
            brokerDevice = indigo.devices[int(brokerID)]
            broker = self.brokers[brokerDevice.id]
            varList = brokerDevice.pluginProps.get(u'published_variables', None)
            if varList and unicode(newVariable.id) in varList:
                var_data = makeVarForJSON(newVariable)
#                self.logger.debug(u"variableUpdated, var_data = {}".format(var_data))
                topic_template =  brokerDevice.pluginProps.get("variable_template_topic", None)
                if not topic_template:
                    return
                topic = pystache.render(topic_template, var_data)
                payload_template = brokerDevice.pluginProps.get("variable_template_payload", None)
                if not payload_template:
                    return
                payload = pystache.render(payload_template, var_data)
                payload = " ".join(re.split("\s+", payload, flags=re.UNICODE)).replace(", }", " }")
                qos = int(brokerDevice.pluginProps.get("variable_template_qos", 1))
                retain = bool(brokerDevice.pluginProps.get("variable_template_retain", False))
#                self.logger.debug(u"variableUpdated, topic = {}, payload = {}".format(topic, payload))
                broker.publish(topic=topic, payload=payload, qos=qos, retain=retain)

        
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


    ########################################
    # Device Management Methods
    ########################################
      
    def deviceStartComm(self, device):
        self.logger.info(u"{}: Starting Device".format(device.name))

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
            self.logger.warning(u"{}: deviceStartComm: Invalid device type: {}".format(device.name, device.deviceTypeId))
        
    
    def deviceStopComm(self, device):
        self.logger.info(u"{}: Stopping Device".format(device.name))
        if device.deviceTypeId == "mqttBroker":
            del self.brokers[device.id]
        else:
            self.logger.warning(u"{}: deviceStopComm: Invalid device type: {}".format(device.name, device.deviceTypeId))
        
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
        for trigger in self.triggers.values():
            if (trigger.pluginProps["brokerID"] == "-1") or (trigger.pluginProps["brokerID"] == str(device.id)):
                if trigger.pluginTypeId == "messageReceived":
                    indigo.trigger.execute(trigger)
                elif trigger.pluginTypeId == "regexMatch":
                    pattern = trigger.pluginProps["regexPattern"]
                    cPattern = re.compile(pattern)
                    match = cPattern.search(device.states["last_topic"])
                    if match:
                        regexMatch = match.group()
                        indigo.trigger.execute(trigger)
                elif trigger.pluginTypeId == "stringMatch":
                    pattern = trigger.pluginProps["stringPattern"]
                    if device.states["last_topic"] == pattern:
                        indigo.trigger.execute(trigger)
                elif trigger.pluginTypeId == "topicMatch":
                    topic_parts = splitall(device.states["last_topic"])
#                    self.logger.debug("{}: topicMatch topics parts = {}".format(trigger.name, topic_parts))
                    last_payload = device.states["last_payload"]
#                    self.logger.debug("{}: topicMatch last_payload ({}) = {}".format(trigger.name, type(last_payload), last_payload))
                    try:
                        payload = json.loads(device.states["last_payload"])
                    except:
                        self.logger.debug("{}: topicMatch json error, payload = {}".format(trigger.name, device.states["last_payload"]))
                        return
                    
                    # got everything, now to check the topics
                    i = 0
                    is_match = True
                    for match in trigger.pluginProps['match_list']:
                        try:                          
                            topic_part = topic_parts[i]
                        except:
                            topic_part = ""
                        i += 1

                        p = match.split(": ")
#                        self.logger.debug("{}: topicMatch match_type = {}, match_string = {}, topic_part = {}".format(trigger.name, p[0], p[1], topic_part))
                        if p[0] == "Skip":
                            continue
                        elif p[0] == "Match":
                            if topic_part == p[1]:
                                continue
                            else:
                                is_match = False
                                break      
                        
                    # here after all items in match_list have been checked, or a match failed
                    if is_match:                    
                        indigo.trigger.execute(trigger)
                    
                else:
                    self.logger.error("Unknown Trigger Type %s (%d), %s" % (trigger.name, trigger.id, trigger.pluginTypeId))


    ########################################
    # Methods for the subscriptions config panel
    ########################################
    
    def addTopic(self, valuesDict, typeId, deviceId):
        topic = valuesDict["subscriptions_newTopic"]
        qos = valuesDict["subscriptions_qos"]
        s = "{}:{}".format(qos, topic)
        topicList = list()
        if 'subscriptions' in valuesDict:
            for t in valuesDict['subscriptions']:
                topicList.append(t) 
        if s not in topicList:
            topicList.append(s)
        valuesDict['subscriptions'] = topicList
        return valuesDict

    def deleteSubscriptions(self, valuesDict, typeId, deviceId):
        topicList = list()
        if 'subscriptions' in valuesDict:
            for t in valuesDict['subscriptions']:
                topicList.append(t) 
        for t in valuesDict['subscriptions_items']:
            if t in topicList:
                topicList.remove(t)
        valuesDict['subscriptions'] = topicList
        return valuesDict

    def subscribedList(self, filter, valuesDict, typeId, deviceId):
        returnList = list()
        if 'subscriptions' in valuesDict:
            for topic in valuesDict['subscriptions']:
                returnList.append(topic)
        return returnList
        

    ########################################
    # Methods for the published devices config panel
    ########################################
    
    def addDevice(self, valuesDict, typeId, deviceId):
        d = valuesDict["devices_deviceSelected"]
        deviceList = list()
        if 'published_devices' in valuesDict:
            for t in valuesDict['published_devices']:
                deviceList.append(t) 
        if d not in deviceList:
            deviceList.append(d)
        valuesDict['published_devices'] = deviceList
        return valuesDict

    def deleteDevices(self, valuesDict, typeId, deviceId):
        deviceList = list()
        if 'published_devices' in valuesDict:
            for t in valuesDict['published_devices']:
                deviceList.append(t) 
        for t in valuesDict['devices_list']:
            if t in deviceList:
                deviceList.remove(t)
        valuesDict['published_devices'] = deviceList
        return valuesDict

    def publishedDeviceList(self, filter, valuesDict, typeId, deviceId):
        returnList = list()
        if 'published_devices' in valuesDict:
            for d in valuesDict['published_devices']:
                try:
                    returnList.append((d, indigo.devices[int(d)].name))
                except:
                    pass
        return returnList
        
    ########################################
    # Methods for the published variables config panel
    ########################################
    
    def addVariable(self, valuesDict, typeId, deviceId):
        d = valuesDict["variables_variableSelected"]
        deviceList = list()
        if 'published_variables' in valuesDict:
            for t in valuesDict['published_variables']:
                deviceList.append(t) 
        if d not in deviceList:
            deviceList.append(d)
        valuesDict['published_variables'] = deviceList
        return valuesDict

    def deleteVariables(self, valuesDict, typeId, deviceId):
        deviceList = list()
        if 'published_variables' in valuesDict:
            for t in valuesDict['published_variables']:
                deviceList.append(t) 
        for t in valuesDict['variables_list']:
            if t in deviceList:
                deviceList.remove(t)
        valuesDict['published_variables'] = deviceList
        return valuesDict

    def publishedVariableList(self, filter, valuesDict, typeId, deviceId):
        returnList = list()
        if 'published_variables' in valuesDict:
            for d in valuesDict['published_variables']:
                try:
                    returnList.append((d, indigo.variables[int(d)].name))
                except:
                    pass
        return returnList

    def getVariables(self, filter="", valuesDict=None, typeId="", targetId=0):
        retList = []
        for var in indigo.variables.iter():
            retList.append((var.id, var.name))

        retList.sort(key=lambda tup: tup[1])
        return retList
        
    ########################################

    def validateDeviceConfigUi(self, valuesDict, typeId, deviceId):
        errorsDict = indigo.Dict()

        if typeId == "mqttBroker": 

            # test the templates to make sure they return valid data
            
                
            # if the subscription list changes, calc changes and update the broker

            if not 'subscriptions' in valuesDict:
                valuesDict['subscriptions'] = indigo.List()
            if not 'old_subscriptions' in valuesDict:
                valuesDict['old_subscriptions'] = indigo.List()
            
            # unsubscribe first in case the QoS changed
            for s in valuesDict['old_subscriptions']:
                if s not in valuesDict['subscriptions']:
                    topic = s[2:]
                    broker.unsubscribe(topic=topic)

            for s in valuesDict['subscriptions']:
                if s not in valuesDict['old_subscriptions']:
                    qos = int(s[0:1])
                    topic = s[2:]
                    broker.subscribe(topic=topic, qos=qos)

            valuesDict['old_subscriptions'] = valuesDict['subscriptions']
        
        else:
            self.logger.warning(u"validateDeviceConfigUi: Invalid device type: {}".format(typeId))

        return (True, valuesDict)

    ########################################
    # Methods for the topic match config panel
    ########################################
    
    def addMatch(self, valuesDict, typeId, deviceId):
        match_type = valuesDict["match_type"]
        match_string = valuesDict["match_string"]
        s = "{}: {}".format(match_type, match_string)
        match_list = list()
        if 'match_list' in valuesDict:
            for t in valuesDict['match_list']:
                match_list.append(t) 
        if s not in match_list:
            match_list.append(s)
        valuesDict['match_list'] = match_list
        valuesDict["match_type"] = "Match"
        valuesDict["match_string"] = ""
        return valuesDict

    def deleteMatches(self, valuesDict, typeId, deviceId):
        match_list = list()
        if 'match_list' in valuesDict:
            for t in valuesDict['match_list']:
                match_list.append(t) 
        for t in valuesDict['match_items']:
            if t in match_list:
                match_list.remove(t)
        valuesDict['match_list'] = match_list
        return valuesDict

    def matchList(self, filter, valuesDict, typeId, deviceId):
        returnList = list()
        if 'match_list' in valuesDict:
            for match in valuesDict['match_list']:
                returnList.append(match)
        return returnList
        

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
        payload = makeDevForJSON(pubDevice)
#        self.logger.debug(u"{}: publishDeviceAction {}: {}, {}, {}".format(brokerDevice.name, topic, payload, qos, retain))
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
        if "Any" in filter:
            retList = [("-1","- Any Broker -")]
        else:
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

    ########################################################################
    # Used to queue waiting messages
    ########################################################################

    def queueMessageForDispatchAction(self, action, device, callerWaitingForResult):

        messageType = action.props["message_type"]
        queue = self.queueDict.get(messageType, None)
        if not queue:
            self.queueDict[messageType] = Queue()

        message =  {
            'version': 0,
            'message_type' : messageType,
            'topic_string' : device.states['last_topic'],
            'payload_json' : device.states['last_payload'] 
        }
            
        self.queueDict[messageType].put(message)
        self.logger.debug(u"{}: queueMessageForDispatchAction, queue = {} ({})".format(device.name, messageType, self.queueDict[messageType].qsize()))
        

    ########################################################################
    # Used to fetch waiting messages
    ########################################################################

    def fetchQueuedMessageAction(self, action, device, callerWaitingForResult):
        messageType = action.props["message_type"]
        queue = self.queueDict.get(messageType, None)
        if not queue or queue.empty():
            return None
        self.logger.debug(u"{}: fetchQueuedMessageAction, queue = {} ({})".format(device.name, messageType, queue.qsize()))
        return queue.get()
    
