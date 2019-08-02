#! /usr/bin/env python
# -*- coding: utf-8 -*-
####################

import logging
import indigo

import paho.mqtt.client as mqtt


################################################################################
class Broker(object):

    def __init__(self, device):
        self.logger = logging.getLogger("Plugin.Broker")
        self.device = device

        self.address = device.pluginProps.get(u'address', "")
        self.port = int(device.pluginProps.get(u'port', 1883))
        self.protocol = int(device.pluginProps.get(u'protocol', 4))
        self.transport = device.pluginProps.get(u'transport', "tcp")

        self.logger.debug(u"Broker __init__ address = {}, port = {}, protocol = {}, transport = {}".format(self.address, self.port, self.protocol, self.transport))
        
        stateList = [
            { 'key':'status',   'value':  "Unknown"},
        ]
        self.device.updateStatesOnServer(stateList)
        self.device.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)

        self.client = mqtt.Client(client_id="", clean_session=True, userdata=None, protocol=self.protocol, transport=self.transport)

        if bool(indigo.activePlugin.pluginPrefs[u"showDebugInfo"]):
            self.logger.debug(u"{}: Enabling library level debugging".format(self.device.name))    
            self.client.enable_logger(self.logger)

        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message
        self.client.on_publish = self.on_publish
        self.client.on_subscribe = self.on_subscribe
        self.client.on_unsubscribe = self.on_unsubscribe

        try:
            self.client.connect(self.address, self.port, 60)
        except:
            stateList = [
                { 'key':'status',   'value':  "Connection Failed"},
            ]
            self.device.updateStatesOnServer(stateList)
            self.device.updateStateImageOnServer(indigo.kStateImageSel.SensorTripped)

            
        
    def __del__(self):
    
        self.client.disconnect()
        
        stateList = [
            { 'key':'status',   'value':  "Disconnected"},
        ]
        self.device.updateStatesOnServer(stateList)
        self.device.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)
      
      
    def loop(self):
        self.client.loop(timeout=1.0)
          
    def publish(self, topic, payload=None, qos=0, retain=False):
        self.client.publish(topic, payload, qos, retain)

    def subscribe(self, topic, qos=0):
        self.client.subscribe(topic, qos)

    def unsubscribe(self, topic):
        self.client.publish(topic)


    ################################################################################
    # Callbacks
    ################################################################################

    def on_connect(self, client, userdata, flags, rc):
        self.logger.debug(u"{}: Connected with result code {}".format(self.device.name, rc))

        # Subscribing in on_connect() means that if we lose the connection and
        # reconnect then subscriptions will be renewed.
#        client.subscribe("#")

        stateList = [
            { 'key':'status',   'value':  "Connected"},
        ]
        self.device.updateStatesOnServer(stateList)
        self.device.updateStateImageOnServer(indigo.kStateImageSel.SensorOn)

    def on_disconnect(self, client, userdata, rc):
        self.logger.debug(u"{}: Disconnected with result code {}".format(self.device.name, rc))
        stateList = [
            { 'key':'status',   'value':  "Disconnected"},
        ]
        self.device.updateStatesOnServer(stateList)
        self.device.updateStateImageOnServer(indigo.kStateImageSel.SensorTripped)

    def on_message(self, client, userdata, msg):
        self.logger.debug(u"{}: Message received: {}, payload: {}".format(self.device.name, msg.topic, msg.payload))

        stateList = [
            { 'key':'last_topic',   'value':  msg.topic},
            { 'key':'last_payload',   'value': msg.payload},
        ]
        self.device.updateStatesOnServer(stateList)
        indigo.activePlugin.triggerCheck(self.device)

    def on_publish(self, client, userdata, mid):
        self.logger.debug(u"{}: Message published: {}".format(self.device.name, mid))

    def on_subscribe(self, client, userdata, mid, granted_qos):
        self.logger.debug(u"{}: Subscribe complete: {}, {}".format(self.device.name, mid, granted_qos))

    def on_unsubscribe(self, client, userdata, mid):
        self.logger.debug(u"{}: Subscribe complete: {}".format(self.device.name, mid))

