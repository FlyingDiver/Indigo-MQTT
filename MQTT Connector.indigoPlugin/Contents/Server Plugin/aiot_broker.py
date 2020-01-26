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
        
        self.device = device
    
        address = device.pluginProps.get(u'address', "")
        port = int(device.pluginProps.get(u'port', ""))
        ca_bundle = indigo.server.getInstallFolderPath() + '/' + device.pluginProps.get(u'ca_bundle', "")
        cert_file = indigo.server.getInstallFolderPath() + '/' + device.pluginProps.get(u'cert_file', "")
        private_key = indigo.server.getInstallFolderPath() + '/' + device.pluginProps.get(u'private_key', "")

        self.logger.debug(u"{}: Broker __init__ address = {}:{}, ca_bundle = {}, cert_file = {}, private_key = {}".format(device.name, address, port, ca_bundle, cert_file, private_key))
        
        self.device.updateStateOnServer(key="status", value="Not Connected")
        self.device.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)

        try: 
            self.aIoTClient = AWSIoTMQTTClient("indigo-mqtt-{}".format(device.id), useWebsocket=False)
            self.aIoTClient.configureEndpoint(address, port)
            self.aIoTClient.configureCredentials(ca_bundle, private_key, cert_file)

            self.aIoTClient.configureAutoReconnectBackoffTime(1, 64, 20)
            self.aIoTClient.configureOfflinePublishQueueing(-1)  # Infinite offline Publish queueing
            self.aIoTClient.configureDrainingFrequency(2)  # Draining: 2 Hz
            self.aIoTClient.configureConnectDisconnectTimeout(10)  # 10 sec
            self.aIoTClient.configureMQTTOperationTimeout(5)  # 5 sec

#            self.aIoTClient.disableMetricsCollection()

            self.aIoTClient.onOnline  = self.onOnline
            self.aIoTClient.onOffline = self.onOffline
            self.aIoTClient.onMessage = self.onMessage


            self.aIoTClient.connectAsync(ackCallback=self.onConnect)

        except:
            self.logger.exception(u"{}: Exception while creating Broker object".format(self.device.name))
                  
            
    def __del__(self):
        self.aIoTClient.disconnect()        
        self.device.updateStateOnServer(key="status", value="Not Connected")
        self.device.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)      
      
    def loop(self):
        pass                        

    def publish(self, topic, payload=None, qos=0, retain=False):
        self.logger.debug(u"{}: Publishing to: {} ({}), payload = {}".format(self.device.name, topic, qos, payload))
        self.aIoTClient.publishAsync(str(topic), str(payload), qos, ackCallback=self.onPublish)

    def subscribe(self, topic, qos=0):
        self.logger.info(u"{}: Subscribing to: {} ({})".format(self.device.name, topic, qos))
        self.aIoTClient.subscribeAsync(str(topic), int(qos), ackCallback=self.onSubscribe)

    def unsubscribe(self, topic):
        self.logger.info(u"{}: Unsubscribing from: {}".format(self.device.name, topic))
        self.aIoTClient.unsubscribeAsync(str(topic), ackCallback=self.onUnsubscribe)

    def refreshFromServer(self):
        self.device.refreshFromServer()

    ################################################################################
    # Callbacks
    ################################################################################

    def onConnect(self, mid, rc):
        self.logger.debug(u"{}: Client Connected, mid = {}, rc = {}".format(self.device.name, mid, rc))
        self.device.refreshFromServer()
        self.device.updateStateOnServer(key="status", value="OnLine")
        self.device.updateStateImageOnServer(indigo.kStateImageSel.SensorOn)

        # Subscribing in onConnect() means that if we lose the connection and reconnect then subscriptions will be renewed.
        subs = self.device.pluginProps.get(u'subscriptions', None)
        if subs:
            for s in subs:
                qos = int(s[0:1])
                topic = s[2:]
                self.subscribe(topic, qos)
            
    def onOnline(self):
        self.logger.debug(u"{}: Client is Online".format(self.device.name))

    def onOffline(self):
        self.logger.debug(u"{}: Client is OffLine".format(self.device.name))
        self.device.updateStateOnServer(key="status", value="OffLine")
        self.device.updateStateImageOnServer(indigo.kStateImageSel.SensorTripped)

    def onTopicMessage(self, client, userdata, msg):
        self.logger.debug(u"{}: onTopicMessage - client: {}, userdata: {} message: '{}', payload: {}".format(self.device.name, client, userdata, msg.topic, msg.payload))


    def onMessage(self, msg):
        self.logger.debug(u"{}: Message received: {}, payload: {}".format(self.device.name, msg.topic, msg.payload))

        stateList = [
            { 'key':'last_topic',   'value': msg.topic   },
            { 'key':'last_payload', 'value': msg.payload }
        ]
        self.device.updateStatesOnServer(stateList)
        indigo.activePlugin.triggerCheck(self.device)

    def onPublish(self, mid):
        self.logger.debug(u"{}: Message published: {}".format(self.device.name, mid))

    def onSubscribe(self, mid, data):
        self.logger.debug(u"{}: Subscribe complete: {}, {}".format(self.device.name, mid, data))

    def onUnsubscribe(self, mid):
        self.logger.debug(u"{}: Unsubscribe complete: {}".format(self.device.name, mid))

