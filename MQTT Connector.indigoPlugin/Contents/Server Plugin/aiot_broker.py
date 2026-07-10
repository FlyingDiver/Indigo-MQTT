#! /usr/bin/env python
# -*- coding: utf-8 -*-
####################

import time
import logging
import indigo

from AWSIoTPythonSDK.MQTTLib import AWSIoTMQTTClient
from subscription_format import decode_subscription


################################################################################
class AIoTBroker(object):

    def __init__(self, device):
        self.logger = logging.getLogger("Plugin.aIoTBroker")

        self.deviceID = device.id
        self.aIoTClient = None  # stays None if client creation below fails

        address = device.pluginProps.get('address', "")
        port = int(device.pluginProps.get('port', 8883))
        ca_bundle = indigo.server.getInstallFolderPath() + '/' + device.pluginProps.get('ca_bundle', "")
        cert_file = indigo.server.getInstallFolderPath() + '/' + device.pluginProps.get('cert_file', "")
        private_key = indigo.server.getInstallFolderPath() + '/' + device.pluginProps.get('private_key', "")

        self.logger.debug(f"{device.name}: Broker __init__ address = {address}:{port}, ca_bundle = {ca_bundle}, cert_file = {cert_file}, private_key = {private_key}")
        
        device.updateStateOnServer(key="status", value="Not Connected")
        device.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)

        try:
            client = AWSIoTMQTTClient("indigo-mqtt-{}".format(device.id), useWebsocket=False)
            client.configureEndpoint(address, port)
            client.configureCredentials(ca_bundle, private_key, cert_file)

            client.configureAutoReconnectBackoffTime(1, 64, 20)
            client.configureOfflinePublishQueueing(-1)  # Infinite offline Publish queueing
            client.configureDrainingFrequency(2)  # Draining: 2 Hz
            client.configureConnectDisconnectTimeout(10)  # 10 sec
            client.configureMQTTOperationTimeout(5)  # 5 sec

            client.disableMetricsCollection()

            client.onOnline  = self.onOnline
            client.onOffline = self.onOffline
            client.onMessage = self.onMessage

            # assign before connectAsync: the onConnect ack callback uses self.aIoTClient
            self.aIoTClient = client
            client.connectAsync(ackCallback=self.onConnect)

        except (Exception,):
            self.logger.exception(f"{device.name}: Exception while creating Broker object")
            self.aIoTClient = None
            device.updateStateOnServer(key="status", value="Connection Failed")
            device.updateStateImageOnServer(indigo.kStateImageSel.SensorTripped)

    def disconnect(self):
        device = indigo.devices[self.deviceID]
        if self.aIoTClient:
            self.aIoTClient.disconnect()
        device.updateStateOnServer(key="status", value="Not Connected")
        device.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)

    def publish(self, topic, payload=None, qos=0, retain=False):
        device = indigo.devices[self.deviceID]
        if not self.aIoTClient:
            self.logger.warning(f"{device.name}: Client not started, unable to publish to {topic}")
            return
        self.logger.debug(u"{}: Publishing to: {} ({}), payload = {}".format(device.name, topic, qos, payload))
        self.aIoTClient.publishAsync(str(topic), str(payload), qos, ackCallback=self.onPublish)

    def subscribe(self, topic, qos=0):
        device = indigo.devices[self.deviceID]
        if not self.aIoTClient:
            self.logger.warning(f"{device.name}: Client not started, unable to subscribe to {topic}")
            return
        self.logger.info(u"{}: Subscribing to: {} ({})".format(device.name, topic, qos))
        self.aIoTClient.subscribeAsync(str(topic), int(qos), ackCallback=self.onSubscribe)

    def unsubscribe(self, topic):
        device = indigo.devices[self.deviceID]
        if not self.aIoTClient:
            self.logger.warning(f"{device.name}: Client not started, unable to unsubscribe from {topic}")
            return
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
        if subs := device.pluginProps.get('subscriptions'):
            for sub in subs:
                qos, topic = decode_subscription(device.deviceTypeId, sub)
                self.subscribe(topic, qos)
            
    def onOnline(self):
        device = indigo.devices[self.deviceID]
        self.logger.debug(u"{}: Client is Online".format(device.name))

    def onOffline(self):
        device = indigo.devices[self.deviceID]
        self.logger.debug(u"{}: Client is OffLine".format(device.name))
        device.updateStateOnServer(key="status", value="OffLine")
        device.updateStateImageOnServer(indigo.kStateImageSel.SensorTripped)

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
