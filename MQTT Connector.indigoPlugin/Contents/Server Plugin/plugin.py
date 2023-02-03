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
from threading import Thread
from queue import Queue, Empty

from mqtt_broker import MQTTBroker
from aiot_broker import AIoTBroker

kCurDevVersCount = 0  # current version of plugin devices


# normally used for file system paths, but will work for slash separated topics
def splitall(path):
    allparts = []
    while True:
        parts = os.path.split(path)
        if parts[0] == path:  # sentinel for absolute paths
            allparts.insert(0, parts[0])
            break
        elif parts[1] == path:  # sentinel for relative paths
            allparts.insert(0, parts[1])
            break
        else:
            path = parts[0]
            allparts.insert(0, parts[1])
    return allparts


def make_dev_dict(device):
    dev_data = {'name': device.name, 'address': device.address, 'deviceId': device.id,
                'deviceTypeId': device.deviceTypeId, 'model': device.model, 'subModel': device.subModel,
                'protocol': device.protocol, 'states': []}

    for key, value in device.states.iteritems():
        dev_data['states'].append({'name': key, 'value': value})
    dev_data['capabilities'] = []
    for key in dir(device):
        if key.find("supports") > -1 and getattr(device, key):
            dev_data['capabilities'].append({'name': key})
    return dev_data


def make_var_dict(variable):
    return {'name': variable.name, 'variableId': variable.id, 'value': variable.value}


def deep_merge_dicts(original, incoming):
    """
    Deep merge two dictionaries. Modifies original.
    For key conflicts if both values are:
     a. dict: Recursively call deep_merge_dicts on both values.
     b. anything else: Value is overridden.
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

        self.aggregators = {}
        self.queueDict = {}
        self.triggers = {}
        self.brokers = {}  # Dict of Indigo MQTT Brokers, indexed by device.id

        self.logLevel = int(pluginPrefs.get("logLevel", logging.INFO))
        self.indigo_log_handler.setLevel(self.logLevel)
        log_format = logging.Formatter('%(asctime)s.%(msecs)03d\t[%(levelname)8s] %(name)20s.%(funcName)-25s%(msg)s',datefmt='%Y-%m-%d %H:%M:%S')
        self.plugin_file_handler.setFormatter(log_format)
        self.plugin_file_handler.setLevel(self.logLevel)
        self.logger.debug(f"MQTT Connector: logLevel = {self.logLevel}")

        self.queueWarning = int(pluginPrefs.get("queueWarning", "30"))
        self.logger.debug(f"MQTT Connector: queueWarning value = {self.queueWarning}")

        savedList = pluginPrefs.get("aggregators", None)
        if savedList:
            self.aggregators = json.loads(savedList)
        else:
            self.aggregators = {}

    def startup(self): # noqa
        indigo.devices.subscribeToChanges()
        indigo.variables.subscribeToChanges()

    def deviceUpdated(self, origDevice, newDevice):
        indigo.PluginBase.deviceUpdated(self, origDevice, newDevice)

        if newDevice.pluginId == self.pluginId:  # can't do updates on own devices
            return

        for brokerID in self.brokers:
            brokerDevice = indigo.devices[int(brokerID)]
            broker = self.brokers[brokerDevice.id]
            devList = brokerDevice.pluginProps.get('published_devices', [])
            doExcludes = brokerDevice.pluginProps.get('devices_doExcludes', False)
            listedDevice = str(newDevice.id) in devList
            self.logger.threaddebug(f"{newDevice.name}: deviceUpdated: doExcludes = {doExcludes}, listedDevice = {listedDevice}")
            self.logger.threaddebug(f"{newDevice.name}: deviceUpdated: id = {newDevice.id}, devList = {devList}")

            if doExcludes and listedDevice:  # excluded, so skip
                continue
            elif (not doExcludes) and (not listedDevice):  # not included, so skip
                continue

            # if we got here, then this device should be published

            dev_data = make_dev_dict(newDevice)
            self.logger.threaddebug(f"{newDevice.name}: deviceUpdated: template data: {dev_data}")
            topic_template = brokerDevice.pluginProps.get("device_template_topic", None)
            if not topic_template:
                self.logger.warning(f"{newDevice.name}: deviceUpdated: unable to publish device, no topic template")
                continue
            topic = pystache.render(topic_template, dev_data)
            payload_template = brokerDevice.pluginProps.get("device_template_payload", None)
            if not payload_template:
                self.logger.warning(f"{newDevice.name}: deviceUpdated: unable to publish device, no payload template")
                continue
            payload = pystache.render(payload_template, dev_data)
            payload = " ".join(re.split(r'\s+', payload, flags=re.UNICODE)).replace(", }", " }")
            payload = " ".join(re.split(r'\s+', payload, flags=re.UNICODE)).replace(", ]", " ]")

            qos = int(brokerDevice.pluginProps.get("device_template_qos", 1))
            retain = bool(brokerDevice.pluginProps.get("device_template_retain", False))
            broker.publish(topic=topic, payload=payload, qos=qos, retain=retain)
            self.logger.threaddebug(f"{newDevice.name}: deviceUpdated: publishing device - payload = {payload}")

    def variableUpdated(self, origVariable, newVariable):
        indigo.PluginBase.variableUpdated(self, origVariable, newVariable)

        for brokerID in self.brokers:
            brokerDevice = indigo.devices[int(brokerID)]
            broker = self.brokers[brokerDevice.id]
            varList = brokerDevice.pluginProps.get('published_variables', [])
            if str(newVariable.id) in varList:
                self.logger.debug(f"{newVariable.name}: variableUpdated: publishing variable")
                var_data = make_var_dict(newVariable)
                topic_template = brokerDevice.pluginProps.get("variable_template_topic", None)
                if not topic_template:
                    self.logger.warning(f"{newVariable.name}: deviceUpdated: unable to publish variable, no topic template")
                    continue
                topic = pystache.render(topic_template, var_data)
                payload_template = brokerDevice.pluginProps.get("variable_template_payload", None)
                if not payload_template:
                    self.logger.warning("{}: deviceUpdated: unable to publish variable, no payload template".format(newVariable.name))
                    continue
                payload = pystache.render(payload_template, var_data)
                payload = " ".join(re.split(r'\s+', payload, flags=re.UNICODE)).replace(", }", " }")

                qos = int(brokerDevice.pluginProps.get("variable_template_qos", 1))
                retain = bool(brokerDevice.pluginProps.get("variable_template_retain", False))
                broker.publish(topic=topic, payload=payload, qos=qos, retain=retain)
                self.logger.threaddebug(f"{newVariable.name}: deviceUpdated: publishing variable - payload = {payload}")

    ########################################
    # Plugin Preference Methods
    ########################################

    def closedPrefsConfigUi(self, valuesDict, userCancelled):
        if not userCancelled:
            self.logLevel = int(valuesDict.get("logLevel", logging.INFO))
            self.indigo_log_handler.setLevel(self.logLevel)
            self.plugin_file_handler.setLevel(self.logLevel)
            self.logger.debug(f"MQTT Connector: logLevel = {self.logLevel}")
            self.queueWarning = int(valuesDict.get("queueWarning", 30))

    ########################################
    # Device Management Methods
    ########################################

    def deviceStartComm(self, device):
        self.logger.info(f"{device.name}: Starting Device")

        instanceVers = int(device.pluginProps.get('devVersCount', 0))
        if instanceVers == kCurDevVersCount:
            self.logger.debug(f"{device.name}: Device is current version: {instanceVers}")
        elif instanceVers < kCurDevVersCount:
            newProps = device.pluginProps
            newProps["devVersCount"] = kCurDevVersCount
            device.replacePluginPropsOnServer(newProps)
            self.logger.debug(f"{device.name}: Updated device version: {instanceVers} -> {kCurDevVersCount}")
        else:
            self.logger.warning(f"{device.name}: Invalid device version: {instanceVers}")

        device.stateListOrDisplayStateIdChanged()

        if device.deviceTypeId == "mqttBroker":
            self.brokers[device.id] = MQTTBroker(device)

        elif device.deviceTypeId == "aIoTBroker":
            self.brokers[device.id] = AIoTBroker(device)

        elif device.deviceTypeId == "dxlBroker":
            try:
                from dxl_broker import DXLBroker
            except ImportError:
                self.logger.warning(f"{device.name}: OpenDXL Client library not installed, unable to start DXL Broker device")
            else:
                self.brokers[device.id] = DXLBroker(device)

        else:
            self.logger.warning(f"{device.name}: deviceStartComm: Invalid device type: {device.deviceTypeId}")

    def deviceStopComm(self, device):
        self.logger.info(f"{device.name}: Stopping Device")
        self.brokers[device.id].disconnect()
        del self.brokers[device.id]
        device.updateStateOnServer(key="status", value="Stopped")
        device.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)

    @staticmethod
    def didDeviceCommPropertyChange(origDev, newDev):

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
            if origDev.pluginProps.get('certFile', None) != newDev.pluginProps.get('certFile', None):
                return True

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

        elif newDev.deviceTypeId == "dxlBroker":
            if origDev.pluginProps.get('address', None) != newDev.pluginProps.get('address', None):
                return True

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
            except ValueError:
                pass
            else:
                payload = json_payload
            return {'topics': {key_string: {'payload': payload}}}

        else:
            split = key_string.split('/', 1)
            key_string = split[0]
            remainder = split[1]
            return {'topics': {key_string: self.recurseAggregator(remainder, payload)}}

    def processReceivedMessage(self, devID, topic, payload):
        device = indigo.devices[devID]
        self.logger.debug(f"{device.name}: processReceivedMessage: {topic}, payload: {payload}")

        # check for topic aggregation

        for aggID in self.aggregators:
            if devID != int(self.aggregators[aggID]['brokerID']):  # skip if wrong broker
                self.logger.threaddebug(f"{device.name}: Wrong broker, devID {devID} != brokerID {self.aggregators[aggID]['brokerID']}")
                continue

            topic_base = self.aggregators[aggID]['topic_base']
            if topic.find(topic_base) == 0:
                remainder = topic[len(topic_base):]
                if remainder[0] == '/':  # not supposed to have a trailing '/', but just in case.
                    remainder = remainder[1:]
                agg_dict = self.recurseAggregator(remainder, payload)
                self.logger.threaddebug(f"{device.name}: agg_dict: {agg_dict}")

                try:
                    payload = json.dumps(deep_merge_dicts(self.aggregators[aggID]['payload'], agg_dict))
                except Exception as e:
                    self.logger.exception(f"Exception {e}")
                topic = topic_base

        # Update broker states
        stateList = [
            {'key': 'last_topic', 'value': topic},
            {'key': 'last_payload', 'value': payload}
        ]
        device.updateStatesOnServer(stateList)
        self.logger.threaddebug(f"{device.name}: Saved states, topic: {topic}, payload: {payload}")

        # look for device or variable commands

        if device.pluginProps.get("control_enable_device_commands", False):
            control_device_pattern = device.pluginProps.get("control_device_pattern", None)
            match = re.match(control_device_pattern, topic)
            if match:
                devId = int(match.group('id'))
                cmd = match.group('cmd').lower()
                self.logger.debug(f"{device.name}: Device command match, DevId: {devId}, command: {cmd}, payload: {payload}")
                if cmd == 'on':
                    indigo.device.turnOn(devId)
                elif cmd == 'off':
                    indigo.device.turnOff(devId)
                elif cmd == 'toggle':
                    indigo.device.toggle(devId)
                elif cmd == 'set' and payload.lower() == 'on':
                    indigo.device.turnOn(devId)
                elif cmd == 'set' and payload.lower() == 'off':
                    indigo.device.turnOff(devId)
                elif cmd == 'brightness':
                    indigo.dimmer.setBrightness(devId, int(payload))
                elif cmd == 'brighten':
                    indigo.dimmer.brighten(devId, int(payload))

        if device.pluginProps.get("control_enable_variable_commands", False):
            control_variable_pattern = device.pluginProps.get("control_variable_pattern", None)
            match = re.match(control_variable_pattern, topic)
            if match:
                varId = int(match.group('id'))
                cmd = match.group('cmd').lower()
                self.logger.debug(f"{device.name}: Variable command match, varId: {varId}, command: {cmd}, payload: {payload}")
                if cmd == 'set':
                    indigo.variable.updateValue(varId, value=payload)
                elif cmd == 'clear':
                    indigo.variable.updateValue(varId, value="")

        # Now do any triggers

        for trigger in self.triggers.values():
            self.logger.debug(f"{trigger.name}: type = {trigger.pluginTypeId}, broker = {trigger.pluginProps['brokerID']}")
            if (trigger.pluginProps["brokerID"] == "-1") or (trigger.pluginProps["brokerID"] == str(device.id)):
                if trigger.pluginTypeId == "messageReceived":
                    indigo.trigger.execute(trigger)

                elif trigger.pluginTypeId == "stringMatch":
                    pattern = trigger.pluginProps["stringPattern"]
                    if topic == pattern:
                        indigo.trigger.execute(trigger)

                elif trigger.pluginTypeId == "topicMatch":
                    topic_parts = splitall(topic)
                    self.logger.threaddebug(f"{trigger.name}: topic_parts = {topic_parts}")
                    self.logger.threaddebug(f"{trigger.name}: match_list = {trigger.pluginProps['match_list']}")
                    comp_index = 0
                    is_match = True
                    for match in trigger.pluginProps['match_list']:
                        p = match.split(": ")
                        self.logger.threaddebug(f"{trigger.name}: match.split = '{p[0]}' '{p[1]}'")

                        if p[0] == "End":
                            self.logger.threaddebug(f"{trigger.name}: End at comp_index = {comp_index}, topic length = {len(topic_parts)}")
                            if len(topic_parts) != comp_index:  # more parts left
                                is_match = False
                                self.logger.threaddebug(f"{trigger.name}: End reached with topic components remaining")
                            break   # always end at 'End'

                        topic_part = topic_parts[comp_index]
                        self.logger.threaddebug(f"{trigger.name}: topic_part {comp_index} = '{topic_part}'")
                        comp_index += 1

                        if p[0] in ["Any", "Skip"]:
                            if not topic_part:  # nothing there to skip
                                is_match = False
                                self.logger.threaddebug(f"{trigger.name}: topic_part empty for required component")
                                break
                            self.logger.threaddebug(f"{trigger.name}: Skipping 'Any' component: '{topic_part}'")

                        elif p[0] == "Match":
                            if topic_part != p[1]:
                                is_match = False
                                self.logger.threaddebug(f"{trigger.name}: Match Failed: '{p[1]}' != '{topic_part}'")
                                break
                            self.logger.threaddebug(f"{trigger.name}: Match OK: '{p[1]}' == '{topic_part}'")

                        else:
                            self.logger.warning(f"{trigger.name}: Unknown Match Type: {p[0]}")

                    self.logger.debug(f"{trigger.name}: Matching complete, is_match = {is_match}")

                    # here after all items in match_list have been checked, or a match failed
                    if is_match:
                        if trigger.pluginProps["queueMessage"]:
                            self.queueMessage(device, trigger.pluginProps["message_type"])
                        indigo.trigger.execute(trigger)

                else:
                    self.logger.error(f"{trigger.name}: Unknown Trigger Type {trigger.pluginTypeId}")

    ########################################
    # Trigger (Event) handling 
    ########################################

    def triggerStartProcessing(self, trigger):
        self.logger.debug(f"{trigger.name}: Adding Trigger")
        assert trigger.id not in self.triggers
        self.triggers[trigger.id] = trigger

    def triggerStopProcessing(self, trigger):
        self.logger.debug(f"{trigger.name}: Removing Trigger")
        assert trigger.id in self.triggers
        del self.triggers[trigger.id]

    ########################################
    # Methods for the subscriptions config panel
    ########################################

    def addTopic(self, valuesDict, typeId, deviceId):
        topic = valuesDict["subscriptions_newTopic"]
        qos = valuesDict["subscriptions_qos"]
        self.logger.debug(f"addTopic: {typeId}, {topic} ({qos})")

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
            self.logger.warning(f"addTopic: Invalid device type: {typeId} for device {deviceId}")

        valuesDict['subscriptions'] = topicList
        return valuesDict

    @staticmethod
    def deleteSubscriptions(valuesDict, typeId, deviceId):
        topicList = list()
        if 'subscriptions' in valuesDict:
            for t in valuesDict['subscriptions']:
                topicList.append(t)
        for t in valuesDict['subscriptions_items']:
            if t in topicList:
                topicList.remove(t)
        valuesDict['subscriptions'] = topicList
        return valuesDict

    @staticmethod
    def subscribedList(ifilter, valuesDict, typeId, deviceId):
        returnList = list()
        if 'subscriptions' in valuesDict:
            for topic in valuesDict['subscriptions']:
                returnList.append(topic)
        return returnList

    ########################################
    # Methods for the published devices config panel
    ########################################

    @staticmethod
    def addDevice(valuesDict, typeId, deviceId):
        d = valuesDict["devices_deviceSelected"]
        deviceList = list()
        if 'published_devices' in valuesDict:
            for t in valuesDict['published_devices']:
                deviceList.append(t)
        if d not in deviceList:
            deviceList.append(d)
        valuesDict['published_devices'] = deviceList
        return valuesDict

    @staticmethod
    def deleteDevices(valuesDict, typeId, deviceId):
        deviceList = list()
        if 'published_devices' in valuesDict:
            for t in valuesDict['published_devices']:
                deviceList.append(t)
        for t in valuesDict['devices_list']:
            if t in deviceList:
                deviceList.remove(t)
        valuesDict['published_devices'] = deviceList
        return valuesDict

    @staticmethod
    def publishedDeviceList(ifilter, valuesDict, typeId, deviceId):
        returnList = list()
        if 'published_devices' in valuesDict:
            for d in valuesDict['published_devices']:
                try:
                    returnList.append((d, indigo.devices[int(d)].name))
                except (Exception,):
                    pass
        return returnList

    ########################################
    # Methods for the published variables config panel
    ########################################

    @staticmethod
    def addVariable(valuesDict, typeId, deviceId):
        d = valuesDict["variables_variableSelected"]
        deviceList = list()
        if 'published_variables' in valuesDict:
            for t in valuesDict['published_variables']:
                deviceList.append(t)
        if d not in deviceList:
            deviceList.append(d)
        valuesDict['published_variables'] = deviceList
        return valuesDict

    @staticmethod
    def deleteVariables(valuesDict, typeId, deviceId):
        deviceList = list()
        if 'published_variables' in valuesDict:
            for t in valuesDict['published_variables']:
                deviceList.append(t)
        for t in valuesDict['variables_list']:
            if t in deviceList:
                deviceList.remove(t)
        valuesDict['published_variables'] = deviceList
        return valuesDict

    @staticmethod
    def publishedVariableList(ifilter, valuesDict, typeId, deviceId):
        returnList = list()
        if 'published_variables' in valuesDict:
            for d in valuesDict['published_variables']:
                try:
                    returnList.append((d, indigo.variables[int(d)].name))
                except Exception as e:
                    pass
        return returnList

    @staticmethod
    def getVariables(ifilter="", valuesDict=None, typeId="", targetId=0):
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

            if 'subscriptions' not in valuesDict:
                valuesDict['subscriptions'] = indigo.List()
            if 'old_subscriptions' not in valuesDict:
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
            except Exception as e:
                self.logger.warning("OpenDXL Client library not installed, unable to create DXL Broker device")
                errorsDict['address'] = "OpenDXL Client library not installed, unable to create DXL Broker device"
                errorsDict['port'] = "OpenDXL Client library not installed, unable to create DXL Broker device"
                return False, valuesDict, errorsDict

            broker = self.brokers.get(deviceId, None)

            # test the templates to make sure they return valid data

            # if the subscription list changes, calc changes and update the broker

            if 'subscriptions' not in valuesDict:
                valuesDict['subscriptions'] = indigo.List()
            if 'old_subscriptions' not in valuesDict:
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

            if 'subscriptions' not in valuesDict:
                valuesDict['subscriptions'] = indigo.List()
            if 'old_subscriptions' not in valuesDict:
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
            self.logger.warning(f"validateDeviceConfigUi: Invalid device type: {typeId}")

        return True, valuesDict

    ########################################
    # Methods for the topic match config panel
    ########################################

    @staticmethod
    def addMatch(valuesDict, typeId, deviceId):
        match_type = valuesDict["match_type"]
        match_string = valuesDict["match_string"]
        s = "{}: {}".format(match_type, match_string)
        match_list = list()
        if 'match_list' in valuesDict:
            for t in valuesDict['match_list']:
                match_list.append(t)
        match_list.append(s)
        valuesDict['match_list'] = match_list
        valuesDict["match_type"] = "Match"
        valuesDict["match_string"] = ""
        return valuesDict

    @staticmethod
    def deleteMatches(valuesDict, typeId, deviceId):
        match_list = list()
        if 'match_list' in valuesDict:
            for t in valuesDict['match_list']:
                match_list.append(t)
        for t in valuesDict['match_items']:
            if t in match_list:
                match_list.remove(t)
        valuesDict['match_list'] = match_list
        return valuesDict

    @staticmethod
    def matchList(ifilter, valuesDict, typeId, deviceId):
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
        self.logger.info(f"{device.name}: Current topic subscriptions:")
        for s in device.pluginProps['subscriptions']:
            qos = int(s[0:1])
            topic = s[2:]
            self.logger.info(f"{device.name}: {topic} ({qos})")
        return True

    # doesn't do anything, just needed to force other menus to dynamically refresh
    @staticmethod
    def menuChanged(valuesDict, typeId, devId):
        return valuesDict

    ########################################
    # Plugin Actions object callbacks (pluginAction is an Indigo plugin action instance)
    ########################################

    def publishMessageAction(self, pluginAction, brokerDevice, callerWaitingForResult):
        broker = self.brokers[brokerDevice.id]
        topic = indigo.activePlugin.substitute(pluginAction.props["topic"])
        payload = indigo.activePlugin.substitute(pluginAction.props["payload"])
        qos = int(pluginAction.props["qos"])
        retain = bool(int(pluginAction.props["retain"]))
        self.logger.threaddebug(f"{brokerDevice.name}: publishMessageAction {topic}: {payload}, {qos}, {retain}")
        broker.publish(topic=topic, payload=payload, qos=qos, retain=retain)

    def publishDeviceAction(self, pluginAction, brokerDevice, callerWaitingForResult):
        broker = self.brokers[brokerDevice.id]
        topic = indigo.activePlugin.substitute(pluginAction.props["topic"])
        qos = int(pluginAction.props["qos"])
        retain = int(pluginAction.props["retain"])
        pubDevice = indigo.devices[int(pluginAction.props["device"])]
        payload = make_dev_dict(pubDevice)
        self.logger.threaddebug(f"{brokerDevice.name}: publishDeviceAction {topic}: {payload}, {qos}, {retain}")
        broker.publish(topic=topic, payload=json.dumps(payload), qos=qos, retain=retain)

    def addSubscriptionAction(self, pluginAction, brokerDevice, callerWaitingForResult):
        topic = indigo.activePlugin.substitute(pluginAction.props["topic"])
        qos = int(pluginAction.props["qos"])
        self.addSubscription(brokerDevice.id, topic, qos)

    def delSubscriptionAction(self, pluginAction, brokerDevice, callerWaitingForResult):
        topic = indigo.activePlugin.substitute(pluginAction.props["topic"])
        self.delSubscription(brokerDevice.id, topic)

    def pickBroker(self, ifilter=None, valuesDict=None, typeId=0, targetId=0):
        if "Any" in ifilter:
            retList = [("-1", "- Any Broker -")]
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
        self.logger.debug(f"{device.name}: addSubscription {topic} ({qos})")

        s = f"{qos}:{topic}"

        updatedPluginProps = device.pluginProps
        if 'subscriptions' not in updatedPluginProps:
            subList = []
        else:
            subList = updatedPluginProps[u'subscriptions']
        if s not in subList:
            subList.append(s)
        updatedPluginProps[u'subscriptions'] = subList
        self.logger.debug(f"{device.name}: subscriptions after update :\n{updatedPluginProps[u'subscriptions']}")
        device.replacePluginPropsOnServer(updatedPluginProps)

    def delSubscription(self, brokerID, topic):
        broker = self.brokers[brokerID]
        device = indigo.devices[int(brokerID)]
        broker.unsubscribe(topic=topic)
        self.logger.debug(u"{}: delSubscription {}".format(device.name, topic))

        updatedPluginProps = device.pluginProps
        if 'subscriptions' not in updatedPluginProps:
            self.logger.error(f"{device.name}: delSubscription error, subList is empty")
            return
        subList = updatedPluginProps[u'subscriptions']
        for sub in subList:
            if topic in sub:
                subList.remove(sub)
                updatedPluginProps[u'subscriptions'] = subList
                self.logger.debug(
                    f"{device.name}: subscriptions after update :\n{updatedPluginProps[u'subscriptions']}")
                device.replacePluginPropsOnServer(updatedPluginProps)
                return

        self.logger.debug(f"{device.name}: Topic {topic} not in subList.")
        return

    ########################################################################
    # This method is called to generate a list of plugin identifiers / names
    ########################################################################

    def getProtocolList(self, ifilter="", valuesDict=None, typeId="", targetId=0):

        retList = []
        indigoInstallPath = indigo.server.getInstallFolderPath()
        pluginsList = os.listdir(indigoInstallPath + '/' + 'Plugins')
        for plugin in pluginsList:
            # Check for Indigo Plugins and exclude 'system' plugins
            if plugin.endswith('.indigoPlugin') and plugin[0:1] != '.':
                # retrieve plugin Info.plist file
                path = f"{indigoInstallPath}/Plugins/{plugin}/Contents/Info.plist"
                with open(path, 'rb') as fp:
                    try:
                        pl = plistlib.load(fp)
                    except Exception as err:
                        self.logger.warning(f"getPluginList: Unable to parse plist, skipping: {path}, err = {err}")
                    else:
                        bundleId = pl["CFBundleIdentifier"]
                        if self.pluginId != bundleId:  # Don't include self (i.e. this plugin) in the plugin list
                            displayName = pl["CFBundleDisplayName"]
                            retList.append((bundleId, displayName))
        retList.sort(key=lambda tup: tup[1])

        retList.insert(0, ("X-10", "X-10"))
        retList.insert(0, ("Z-Wave", "Z-Wave"))
        retList.insert(0, ("Insteon", "Insteon"))
        return retList

    @staticmethod
    def getProtocolDevices(ifilter="", valuesDict=None, typeId="", targetId=0):

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
        self.queueMessage(device, action.props["message_type"])

    def queueMessage(self, device, messageType):
        queue = self.queueDict.get(messageType, None)
        if not queue:
            queue = Queue()
            self.queueDict[messageType] = queue

        message = {
            'version': 0,
            'message_type': messageType,
            'topic_parts': splitall(device.states["last_topic"]),
            'payload': device.states['last_payload']
        }
        queue.put(message)
        self.logger.threaddebug(f"{device.name}: queueMessage, queue = {messageType} ({queue.qsize()})")
        indigo.server.broadcastToSubscribers("com.flyingdiver.indigoplugin.mqtt-message_queued", {'message_type': messageType, 'brokerID': device.id})
        if queue.qsize() > self.queueWarning:
            self.logger.warning(f"Queue for message type '{messageType}' has {queue.qsize()} messages pending")

    ########################################################################
    # Fetch waiting messages
    ########################################################################

    def fetchQueuedMessageAction(self, action, device, callerWaitingForResult):
        messageType = action.props["message_type"]
        queue = self.queueDict.get(messageType, None)
        if not queue or queue.empty():
            return None
        self.logger.threaddebug(f"{device.name}: fetchQueuedMessageAction, queue = {messageType} ({queue.qsize()})")
        return queue.get()

    ########################################################################

    def getBrokerDevices(self, ifilter="", valuesDict=None, typeId="", targetId=0):
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

        aggID = f"{brokerID}:{topic_base}"
        aggItem = {"brokerID": brokerID, "topic_base": topic_base, "payload": {}}
        self.logger.debug(f"Adding aggItem {aggID}: {aggItem}")
        self.aggregators[aggID] = aggItem
        self.logAggregators()

        indigo.activePlugin.pluginPrefs["aggregators"] = json.dumps(self.aggregators)

    ########################################
    # This is the method that's called by the Delete Device button
    ########################################
    def deleteAggregator(self, valuesDict, typeId=None, devId=None):

        for item in valuesDict["aggregatorList"]:
            self.logger.info(u"deleting device {}".format(item))
            del self.aggregators[item]

        self.logAggregators()
        indigo.activePlugin.pluginPrefs["aggregators"] = json.dumps(self.aggregators)

    def aggregatorList(self, ifilter="", valuesDict=None, typeId="", targetId=0):
        returnList = list()
        for aggID in self.aggregators:
            returnList.append((aggID, aggID))
        return sorted(returnList, key=lambda item: item[1])

    ########################################

    def logAggregators(self):
        if len(self.aggregators) == 0:
            self.logger.info("No Aggregators defined")
            return

        fstring = "{:^50}{:^50}{}"
        self.logger.info(fstring.format("Aggregator ID", "Topic Base", "Payload"))
        for aggID, aggItem in self.aggregators.items():
            self.logger.info(fstring.format(aggID, aggItem["topic_base"], json.dumps(aggItem.get("payload", None), sort_keys=True, indent=4, separators=(',', ': '))))
