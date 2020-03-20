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

from mqtt_broker import MQTTBroker
from aiot_broker import AIoTBroker

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
    
def deep_merge_dicts(original, incoming):
    """
    Deep merge two dictionaries. Modifies original.
    For key conflicts if both values are:
     a. dict: Recursively call deep_merge_dicts on both values.
     b. list: Call deep_merge_lists on both values.
     c. any other type: Value is overridden.
     d. conflicting types: Value is overridden.

    """    
    for key in incoming:
        if key in original:
            if isinstance(original[key], dict) and isinstance(incoming[key], dict):
                deep_merge_dicts(original[key], incoming[key])
            else:
                original[key] = incoming[key]
        else:
            original[key] = incoming[key]
    return original
            
################################################################################
class Plugin(indigo.PluginBase):

    def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs):
        indigo.PluginBase.__init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs)

        pfmt = logging.Formatter('%(asctime)s.%(msecs)03d\t[%(levelname)8s] %(name)20s.%(funcName)-25s%(msg)s', datefmt='%Y-%m-%d %H:%M:%S')
        self.plugin_file_handler.setFormatter(pfmt)

        self.logLevel = int(self.pluginPrefs.get(u"logLevel", logging.INFO))
        self.indigo_log_handler.setLevel(self.logLevel)

        self.logger.debug(u"MQTT Connector: logLevel = {}".format(self.logLevel))

    def startup(self):
        self.logger.info(u"Starting MQTT Connector")

        self.brokers = {}            # Dict of Indigo MQTT Brokers, indexed by device.id
        self.triggers = {}
        self.queueDict = {}
        
        savedList = indigo.activePlugin.pluginPrefs.get(u"aggregators", None)
        if savedList:
            self.aggregators = json.loads(savedList)
        else:
            self.aggregators = {}        

        indigo.devices.subscribeToChanges()
        indigo.variables.subscribeToChanges()
                            
    def shutdown(self):
        self.logger.info(u"Shutting down MQTT Connector")

#   No runConcurrentThread since all brokers are running in their own threads and using callbacks.

#     def runConcurrentThread(self):
#         try:
#             while True:
#               
#         except self.StopThread:
#             pass        
            

    def deviceUpdated(self, origDevice, newDevice):
        indigo.PluginBase.deviceUpdated(self, origDevice, newDevice)
        
        if newDevice.pluginId == self.pluginId:          # can't do updates on own devices
            return      

        for brokerID in self.brokers:
            brokerDevice = indigo.devices[int(brokerID)]
            broker = self.brokers[brokerDevice.id]
            devList = brokerDevice.pluginProps.get(u'published_devices', [])
            doExcludes = brokerDevice.pluginProps.get(u'devices_doExcludes', False)
            listedDevice = unicode(newDevice.id) in devList
            self.logger.threaddebug(u"{}: deviceUpdated: doExcludes = {}, listedDevice = {}".format(newDevice.name, doExcludes, listedDevice))
            self.logger.threaddebug(u"{}: deviceUpdated: id = {}, devList = {}".format(newDevice.name, newDevice.id, devList))

            if doExcludes and listedDevice:                     # excluded, so skip
                return      
            elif (not doExcludes) and (not listedDevice):       # not included, so skip
                return
                
            # if we got here, then this device should be published
            
            dev_data = makeDevForJSON(newDevice)
            topic_template =  brokerDevice.pluginProps.get("device_template_topic", None)
            if not topic_template:
                self.logger.debug(u"{}: deviceUpdated: unable to publish device, no topic template".format(newDevice.name))
                return
            topic = pystache.render(topic_template, dev_data)
            payload_template = brokerDevice.pluginProps.get("device_template_payload", None)
            if not payload_template:
                self.logger.debug(u"{}: deviceUpdated: unable to publish device, no payload template".format(newDevice.name))
                return
            payload = pystache.render(payload_template, dev_data)
            payload = " ".join(re.split("\s+", payload, flags=re.UNICODE)).replace(", }", " }")
            self.logger.debug(u"{}: deviceUpdated: publishing device - payload = {}".format(newDevice.name, payload))

            qos = int(brokerDevice.pluginProps.get("device_template_qos", 1))
            retain = bool(brokerDevice.pluginProps.get("device_template_retain", False))
            broker.publish(topic=topic, payload=payload, qos=qos, retain=retain)

    def variableUpdated(self, origVariable, newVariable):
        indigo.PluginBase.variableUpdated(self, origVariable, newVariable)
        
        for brokerID in self.brokers:
            brokerDevice = indigo.devices[int(brokerID)]
            broker = self.brokers[brokerDevice.id]
            varList = brokerDevice.pluginProps.get(u'published_variables', [])
            if unicode(newVariable.id) in varList:
                self.logger.debug(u"{}: variableUpdated: publishing variable".format(newVariable.name))
                var_data = makeVarForJSON(newVariable)
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
            self.brokers[device.id] = MQTTBroker(device)
            
        elif device.deviceTypeId == "aIoTBroker": 
            self.brokers[device.id] = AIoTBroker(device)
            
        elif device.deviceTypeId == "dxlBroker": 
            try:
                from dxl_broker import DXLBroker
            except:
                self.logger.warning(u"{}: OpenDXL Client library not installed, unable to create DXL Broker device".format(device.name))        
            else:
                self.brokers[device.id] = DXLBroker(device)
            
        else:
            self.logger.warning(u"{}: deviceStartComm: Invalid device type: {}".format(device.name, device.deviceTypeId))
        
    
    def deviceStopComm(self, device):
        self.logger.info(u"{}: Stopping Device".format(device.name))
        if device.deviceTypeId in ["mqttBroker", "dxlBroker", "aIoTBroker"]:
            del self.brokers[device.id]
            device.updateStateOnServer(key="status", value="Stopped")
            device.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)      
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
            try:                
                self.brokers[newDev.id].refreshFromServer()
            except:
                pass
                
        elif newDev.deviceTypeId == "AIoTBroker":
            if origDev.pluginProps.get('address', None) != newDev.pluginProps.get('address', None):
                return True           
            if origDev.pluginProps.get('port', None) != newDev.pluginProps.get('port', None):
                return True           
            if origDev.pluginProps.get('ca_bundle', None) != newDev.pluginProps.get('ca_bundle', None):
                return True           
            if origDev.pluginProps.get('cert_file', None) != newDev.pluginProps.get('cert_file', None):
                return True           
            if origDev.pluginProps.get('private_key', None) != newDev.pluginProps.get('private_key', None):
                return True           

            # a bit of a hack to make sure name changes get pushed down immediately
            try:                
                self.brokers[newDev.id].refreshFromServer()
            except:
                pass
                
        elif newDev.deviceTypeId == "dxlBroker":
            if origDev.pluginProps.get('address', None) != newDev.pluginProps.get('address', None):
                return True           

            # a bit of a hack to make sure name changes get pushed down immediately
            try:                
                self.brokers[newDev.id].refreshFromServer()
            except:
                pass
                
        elif newDev.deviceTypeId == "aggregator": 
            return False

        return False
    
    ########################################
    # Message received handling
    ########################################

    def recurseAggregator(self, key_string, payload):
        if '/' not in key_string:
            try:
                json_payload = json.loads(payload)
            except:
                pass
            else:
                payload = json_payload
            return { 'topics': { key_string : { u'payload' : payload }}}
        
        else:
            split = key_string.split('/', 1)
            key_string = split[0]
            remainder = split[1]                
            return { u'topics': { key_string : self.recurseAggregator(remainder, payload) }}              
    
    
    def processReceivedMessage(self, devID, topic, payload):
        device = indigo.devices[devID]
        self.logger.debug(u"{}: Message received: {}, payload: {}".format(device.name, topic, payload))

        # check for topic aggregation
        
        for aggID in self.aggregators:
            if devID != int(self.aggregators[aggID]['brokerID']):   # skip if wrong broker
                self.logger.threaddebug(u"{}: Wrong broker, devID {} != brokerID {}".format(device.name, devID, self.aggregators[aggID]['brokerID']))
                continue
            
            topic_base = self.aggregators[aggID]['topic_base']
            if topic.find(topic_base) == 0:
                remainder = topic[len(topic_base):]
                if remainder[0] == '/':                 # not supposed to have a trailing '/', but just in case.
                    remainder = remainder[1:]
                agg_dict = self.recurseAggregator(remainder, payload)
                self.logger.debug(u"{}: agg_dict: {}".format(device.name, agg_dict))
                
                try:
                    payload = json.dumps(deep_merge_dicts(self.aggregators[aggID]['payload'], agg_dict))
                except Exception as e:
                    self.logger.exception("Exception {}".format(e))
                topic = topic_base
               
        stateList = [
            { 'key':'last_topic',   'value': topic },
            { 'key':'last_payload', 'value': payload }
        ]    
        device.updateStatesOnServer(stateList)
        self.logger.debug(u"{}: Saved states, topic: {}, payload: {}".format(device.name, topic, payload))
        
        # Now do any triggers

        for trigger in self.triggers.values():
            if (trigger.pluginProps["brokerID"] == "-1") or (trigger.pluginProps["brokerID"] == str(device.id)):
                if trigger.pluginTypeId == "messageReceived":
                    indigo.trigger.execute(trigger)
                    
                elif trigger.pluginTypeId == "stringMatch":
                    pattern = trigger.pluginProps["stringPattern"]
                    if topic == pattern:
                        indigo.trigger.execute(trigger)
                        
                elif trigger.pluginTypeId == "topicMatch":
                    topic_parts = splitall(topic)
                    i = 0
                    is_match = True
                    for match in trigger.pluginProps['match_list']:
                        try:                          
                            topic_part = topic_parts[i]
                        except:
                            topic_part = None
                        i += 1
                        p = match.split(": ")
                        if p[0] in ["Any", "Skip"]:
                            if not topic_part:      # nothing there to skip
                                is_match = False
                                break
                        elif p[0] == "End":
                            if topic_part:      # more parts left
                                is_match = False
                            break                                
                        elif p[0] == "Match":
                            if topic_part != p[1]:
                                is_match = False
                                break    
                        
                    # here after all items in match_list have been checked, or a match failed
                    if is_match:        
                        if trigger.pluginProps["queueMessage"]:
                            self.queueLastMessage(device, trigger.pluginProps["message_type"])
                        indigo.trigger.execute(trigger)
                    
                else:
                    self.logger.error("{}: Unknown Trigger Type {}".format(trigger.name, trigger.pluginTypeId))
    
    ########################################
    # Trigger (Event) handling 
    ########################################

    def triggerStartProcessing(self, trigger):
        self.logger.debug("{}: Adding Trigger".format(trigger.name))
        assert trigger.id not in self.triggers
        self.triggers[trigger.id] = trigger

    def triggerStopProcessing(self, trigger):
        self.logger.debug("{}: Removing Trigger".format(trigger.name))
        assert trigger.id in self.triggers
        del self.triggers[trigger.id]


    ########################################
    # Methods for the subscriptions config panel
    ########################################
    
    def addTopic(self, valuesDict, typeId, deviceId):
        topic = valuesDict["subscriptions_newTopic"]
        qos = valuesDict["subscriptions_qos"]
        self.logger.debug(u"addTopic: {}, {} ({})".format(typeId, topic, qos))

        topicList = list()
        if 'subscriptions' in valuesDict:
            for t in valuesDict['subscriptions']:
                topicList.append(t) 

        if typeId == 'dxlBroker':
            if topic not in topicList:
                topicList.append(topic)

        elif typeId == 'mqttBroker':
            s = "{}:{}".format(qos, topic)
            if s not in topicList:
                topicList.append(s)
                
        elif typeId == 'aIoTBroker':
            s = "{}:{}".format(qos, topic)
            if s not in topicList:
                topicList.append(s)
        else:
            self.logger.warning(u"addTopic: Invalid device type: {} for device {}".format(typeId, deviceId))
                
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
            broker = self.brokers.get(deviceId, None)
    
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
                    if broker:
                        broker.unsubscribe(topic=topic)

            for s in valuesDict['subscriptions']:
                if s not in valuesDict['old_subscriptions']:
                    qos = int(s[0:1])
                    topic = s[2:]
                    if broker:
                        broker.subscribe(topic=topic, qos=qos)

            valuesDict['old_subscriptions'] = valuesDict['subscriptions']
        
        elif typeId == "dxlBroker": 
            try:
                from dxl_broker import DXLBroker
            except:
                self.logger.warning(u"OpenDXL Client library not installed, unable to create DXL Broker device")        
                errorsDict['address'] = u"OpenDXL Client library not installed, unable to create DXL Broker device"
                errorsDict['port'] = u"OpenDXL Client library not installed, unable to create DXL Broker device"
                return (False, valuesDict, errorsDict)

            broker = self.brokers.get(deviceId, None)

            # test the templates to make sure they return valid data
        
            
            # if the subscription list changes, calc changes and update the broker

            if not 'subscriptions' in valuesDict:
                valuesDict['subscriptions'] = indigo.List()
            if not 'old_subscriptions' in valuesDict:
                valuesDict['old_subscriptions'] = indigo.List()
        
            # unsubscribe first in case the QoS changed
            for s in valuesDict['old_subscriptions']:
                if s not in valuesDict['subscriptions']:
                    if broker:
                        broker.unsubscribe(topic=s)

            for s in valuesDict['subscriptions']:
                if s not in valuesDict['old_subscriptions']:
                    if broker:
                        broker.subscribe(topic=s)

            valuesDict['old_subscriptions'] = valuesDict['subscriptions']
        
        elif typeId == "aIoTBroker": 
            broker = self.brokers.get(deviceId, None)
    
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
                    if broker:
                        broker.unsubscribe(topic=topic)

            for s in valuesDict['subscriptions']:
                if s not in valuesDict['old_subscriptions']:
                    qos = int(s[0:1])
                    topic = s[2:]
                    if broker:
                        broker.subscribe(topic=topic, qos=qos)

            valuesDict['old_subscriptions'] = valuesDict['subscriptions']

        elif typeId == "aggregator": 
            pass
        
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
        self.logger.threaddebug(u"{}: publishMessageAction {}: {}, {}, {}".format(brokerDevice.name, topic, payload, qos, retain))
        broker.publish(topic=topic, payload=payload, qos=qos, retain=retain)

    def publishDeviceAction(self, pluginAction, brokerDevice, callerWaitingForResult):
        broker = self.brokers[brokerDevice.id]
        topic = indigo.activePlugin.substitute(pluginAction.props["topic"])
        qos = int(pluginAction.props["qos"])
        retain = int(pluginAction.props["retain"])
        pubDevice = indigo.devices[int(pluginAction.props["device"])]
        payload = makeDevForJSON(pubDevice)
        self.logger.threaddebug(u"{}: publishDeviceAction {}: {}, {}, {}".format(brokerDevice.name, topic, payload, qos, retain))
        broker.publish(topic=topic, payload=json.dumps(payload), qos=qos, retain=retain)

    def addSubscriptionAction(self, pluginAction, brokerDevice, callerWaitingForResult):
        topic = indigo.activePlugin.substitute(pluginAction.props["topic"])
        qos = int(pluginAction.props["qos"])
        self.addSubscription(brokerDevice.id, topic, qos)

    def delSubscriptionAction(self, pluginAction, brokerDevice, callerWaitingForResult):
        topic = indigo.activePlugin.substitute(pluginAction.props["topic"])
        self.delSubscription(brokerDevice.id, topic)


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
        
        s = "{}:{}".format(qos, topic)

        updatedPluginProps = device.pluginProps
        if not 'subscriptions' in updatedPluginProps:
           subList = []
        else:
           subList = updatedPluginProps[u'subscriptions']
        if not s in subList:
            subList.append(s)
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
        for sub in subList:
            if topic in sub:
                subList.remove(sub)      
                updatedPluginProps[u'subscriptions'] = subList
                self.logger.debug(u"{}: subscriptions after update :\n{}".format(device.name, updatedPluginProps[u'subscriptions']))
                device.replacePluginPropsOnServer(updatedPluginProps)
                return
                
        self.logger.debug(u"{}: Topic {} not in subList.".format(device.name, topic))
        return


    ########################################################################
    # This method is called to generate a list of plugin identifiers / names
    ########################################################################

    def getProtocolList(self, filter="", valuesDict=None, typeId="", targetId=0):

        retList = []
        indigoInstallPath = indigo.server.getInstallFolderPath()
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
    # Queue waiting messages
    ########################################################################

    def queueMessageForDispatchAction(self, action, device, callerWaitingForResult):
        self.queueLastMessage(device, action.props["message_type"])
        
        
    def queueLastMessage(self, device, messageType):
        queue = self.queueDict.get(messageType, None)
        if not queue:
            queue = Queue()
            self.queueDict[messageType] = queue

        message =  {
            'version': 0,
            'message_type' : messageType,
            'topic_parts'  : splitall(device.states["last_topic"]),
            'payload' : device.states['last_payload'] 
        }
        queue.put(message)
        self.logger.threaddebug(u"{}: queueLastMessage, queue = {} ({})".format(device.name, messageType, queue.qsize()))
        indigo.server.broadcastToSubscribers(u"com.flyingdiver.indigoplugin.mqtt-message_queued", {'message_type' : messageType, 'brokerID': device.id})        
        if queue.qsize() > 10:
            self.logger.warning("Queue for message type '{}' has {} messages pending".format(messageType, queue.qsize()))
            
    ########################################################################
    # Fetch waiting messages
    ########################################################################

    def fetchQueuedMessageAction(self, action, device, callerWaitingForResult):
        messageType = action.props["message_type"]
        queue = self.queueDict.get(messageType, None)
        if not queue or queue.empty():
            return None
        self.logger.threaddebug(u"{}: fetchQueuedMessageAction, queue = {} ({})".format(device.name, messageType, queue.qsize()))
        return queue.get()

    ########################################################################
    
    def getBrokerDevices(self, filter="", valuesDict=None, typeId="", targetId=0):
        retList = []
        for brokerID in self.brokers:
            device = indigo.devices[int(brokerID)]
            retList.append((device.id, device.name))
        retList.sort(key=lambda tup: tup[1])
        return retList
    
    ########################################
    # This is the method that's called by the Add Aggregator button in the config dialog.
    ########################################
    def addAggregator(self, valuesDict, typeId=None, devId=None):
        
        brokerID = valuesDict["brokerID"]
        topic_base = valuesDict["topic_base"]

        aggID = "{}:{}".format(brokerID, topic_base)
        aggItem = {"brokerID" : brokerID, "topic_base" : topic_base, "payload" : {}}
        self.logger.debug(u"Adding aggItem {}: {}".format(aggID, aggItem))
        self.aggregators[aggID] = aggItem
        self.logAggregators()
        
        indigo.activePlugin.pluginPrefs[u"aggregators"] = json.dumps(self.aggregators)

    ########################################
    # This is the method that's called by the Delete Device button
    ########################################
    def deleteAggregator(self, valuesDict, typeId=None, devId=None):
        
        for item in valuesDict["aggregatorList"]:
            self.logger.info(u"deleting device {}".format(item))
            del self.aggregators[item]

        self.logAggregators()
        indigo.activePlugin.pluginPrefs[u"aggregators"] = json.dumps(self.aggregators)
        
    def aggregatorList(self, filter="", valuesDict=None, typeId="", targetId=0):
        returnList = list()
        for aggID in self.aggregators:
            returnList.append((aggID, aggID))
        return sorted(returnList, key= lambda item: item[1])
            
    ########################################

    def logAggregators(self):
        if len(self.aggregators) == 0:
            self.logger.info(u"No Aggregators defined")
            return
            
        fstring = u"{:^35}{:^35}{}"
        self.logger.info(fstring.format("Aggregator ID", "Topic Base", "Payload"))
        for aggID, aggItem in self.aggregators.iteritems():
             self.logger.info(fstring.format(aggID, aggItem["topic_base"], json.dumps(aggItem.get("payload", None), sort_keys=True, indent=4, separators=(',', ': '))))
