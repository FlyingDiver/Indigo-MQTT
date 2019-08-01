#! /usr/bin/env python
# -*- coding: utf-8 -*-
####################

import time
import socket
import json
import logging
import requests
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
        self.logger.info(u"Starting MQTT Client")

        self.brokers = {}            # Dict of Indigo MQTT Brokers, indexed by device.id
        
                    
    def shutdown(self):
        self.logger.info(u"Shutting down MQTT Client")


    def runConcurrentThread(self):

        try:
            while True:
            
                self.sleep(1.0)

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
            self.logger.debug(u"MQTT Client logLevel = " + str(self.logLevel))


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
            device.updateStateImageOnServer(indigo.kStateImageSel.SensorOn)

        else:
            self.logger.warning(u"{}: Invalid device type: {}".format(device.name, device.deviceTypeId))

            
    
    def deviceStopComm(self, device):
        self.logger.debug(u"{}: Stopping Device".format(device.name))
        if device.deviceTypeId == "mqttBroker":
            del self.weatherlinks[device.id]
            
            
    def getDeviceDisplayStateId(self, device):
            
        try:
            status_state = device.pluginProps['status_state']
        except:
            status_state = indigo.PluginBase.getDeviceDisplayStateId(self, device)
            
        self.logger.debug(u"{}: getDeviceDisplayStateId returning: {}".format(device.name, status_state))

        return status_state
    

    def pickBroker(self, filter=None, valuesDict=None, typeId=0, targetId=0):
        retList = []
        for broker in self.brokers.values():
            retList.append((broker.device.id, broker.device.name))
        retList.sort(key=lambda tup: tup[1])
        return retList


    ########################################
    # Menu Methods
    ########################################

        
    # doesn't do anything, just needed to force other menus to dynamically refresh
    def menuChanged(self, valuesDict, typeId, devId):
        return valuesDict


