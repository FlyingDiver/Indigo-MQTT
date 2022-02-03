#! /usr/bin/env python
# -*- coding: utf-8 -*-
####################

import time
import logging
import indigo

from AWSIoTPythonSDK.MQTTLib import AWSIoTMQTTClient


################################################################################
class AIoTBroker(object):

    def __init__(self, device):
        self.logger = logging.getLogger("Plugin.aIoTBroker")
        self.logger.setLevel(logging.DEBUG)
        streamHandler = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        streamHandler.setFormatter(formatter)
        self.logger.addHandler(streamHandler)
        
        self.deviceID = device.id
    
        address = device.pluginProps.get(u'address', "")
        port = int(device.pluginProps.get(u'port', ""))
        ca_bundle = indigo.server.getInstallFolderPath() + '/' + device.pluginProps.get(u'ca_bundle', "")
        cert_file = indigo.server.getInstallFolderPath() + '/' + device.pluginProps.get(u'cert_file', "")
        private_key = indigo.server.getInstallFolderPath() + '/' + device.pluginProps.get(u'private_key', "")

        self.logger.debug(f"{device.name}: Broker __init__ address = {address}:{port}, ca_bundle = {ca_bundle}, cert_file = {cert_file}, private_key = {private_key}")
        
        device.updateStateOnServer(key="status", value="Not Connected")
        device.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)

        try: 
            self.aIoTClient = AWSIoTMQTTClient("indigo-mqtt-{}".format(device.id), useWebsocket=False)
            self.aIoTClient.configureEndpoint(address, port)
            self.aIoTClient.configureCredentials(ca_bundle, private_key, cert_file)

            self.aIoTClient.configureAutoReconnectBackoffTime(1, 64, 20)
            self.aIoTClient.configureOfflinePublishQueueing(-1)  # Infinite offline Publish queueing
            self.aIoTClient.configureDrainingFrequency(2)  # Draining: 2 Hz
            self.aIoTClient.configureConnectDisconnectTimeout(10)  # 10 sec
            self.aIoTClient.configureMQTTOperationTimeout(5)  # 5 sec

            self.aIoTClient.disableMetricsCollection()

            self.aIoTClient.onOnline  = self.onOnline
            self.aIoTClient.onOffline = self.onOffline
            self.aIoTClient.onMessage = self.onMessage

            self.aIoTClient.connectAsync(ackCallback=self.onConnect)

        except (Exception,):
            self.logger.exception(f"{device.name}: Exception while creating Broker object")

    def disconnect(self):
        device = indigo.devices[self.deviceID]
        self.aIoTClient.disconnect()        
        device.updateStateOnServer(key="status", value="Not Connected")
        device.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)              
      
    def publish(self, topic, payload=None, qos=0, retain=False):
        device = indigo.devices[self.deviceID]
        self.logger.debug(u"{}: Publishing to: {} ({}), payload = {}".format(device.name, topic, qos, payload))
        self.aIoTClient.publishAsync(str(topic), str(payload), qos, ackCallback=self.onPublish)

    def subscribe(self, topic, qos=0):
        device = indigo.devices[self.deviceID]
        self.logger.info(u"{}: Subscribing to: {} ({})".format(device.name, topic, qos))
        self.aIoTClient.subscribeAsync(str(topic), int(qos), ackCallback=self.onSubscribe)

    def unsubscribe(self, topic):
        device = indigo.devices[self.deviceID]
        self.logger.info(u"{}: Unsubscribing from: {}".format(device.name, topic))
        self.aIoTClient.unsubscribeAsync(str(topic), ackCallback=self.onUnsubscribe)

    ################################################################################
    # Callbacks
    ################################################################################

    def onConnect(self, mid, rc):
        device = indigo.devices[self.deviceID]
        self.logger.debug(u"{}: Client Connected, mid = {}, rc = {}".format(device.name, mid, rc))
        device.updateStateOnServer(key="status", value="OnLine")
        device.updateStateImageOnServer(indigo.kStateImageSel.SensorOn)

        # Subscribing in onConnect() means that if we lose the connection and reconnect then subscriptions will be renewed.
        subs = device.pluginProps.get(u'subscriptions', None)
        if subs:
            for s in subs:
                qos = int(s[0:1])
                topic = s[2:]
                self.subscribe(topic, qos)
            
    def onOnline(self):
        device = indigo.devices[self.deviceID]
        self.logger.debug(u"{}: Client is Online".format(device.name))

    def onOffline(self):
        device = indigo.devices[self.deviceID]
        self.logger.debug(u"{}: Client is OffLine".format(device.name))
        device.updateStateOnServer(key="status", value="OffLine")
        device.updateStateImageOnServer(indigo.kStateImageSel.SensorTripped)

    def onTopicMessage(self, client, userdata, msg):
        device = indigo.devices[self.deviceID]
        self.logger.debug(u"{}: onTopicMessage - client: {}, userdata: {} message: '{}', payload: {}".format(device.name, client, userdata, msg.topic, msg.payload))

    def onMessage(self, msg):
        device = indigo.devices[self.deviceID]
        self.logger.debug(u"{}: Message received: {}, payload: {}".format(device.name, msg.topic, msg.payload))
        indigo.activePlugin.processReceivedMessage(device.id, msg.topic, msg.payload)

    def onPublish(self, mid):
        device = indigo.devices[self.deviceID]
        self.logger.debug(u"{}: Message published: {}".format(device.name, mid))

    def onSubscribe(self, mid, data):
        device = indigo.devices[self.deviceID]
        self.logger.debug(u"{}: Subscribe complete: {}, {}".format(device.name, mid, data))

    def onUnsubscribe(self, mid):
        device = indigo.devices[self.deviceID]
        self.logger.debug(u"{}: Unsubscribe complete: {}".format(device.name, mid))
