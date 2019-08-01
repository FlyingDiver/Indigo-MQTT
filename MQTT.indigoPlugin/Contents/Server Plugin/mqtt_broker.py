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
        
        self.client = mqtt.Client(client_id="", clean_session=True, userdata=None, protocol=self.protocol, transport=self.transport)

        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message

        self.client.connect(self.address, self.port, 60)

        
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


    # The callback for when the client receives a CONNACK response from the server.
    def on_connect(self, client, userdata, flags, rc):
        self.logger.debug(u"{}: Connected with result code {}".format(self.device.name, rc))

        # Subscribing in on_connect() means that if we lose the connection and
        # reconnect then subscriptions will be renewed.
        client.subscribe("#")

        stateList = [
            { 'key':'status',   'value':  "Connected"},
        ]
        self.device.updateStatesOnServer(stateList)
        self.device.updateStateImageOnServer(indigo.kStateImageSel.SensorOn)


    # The callback for when a PUBLISH message is received from the server.
    def on_message(self, client, userdata, msg):
        self.logger.debug(u"{}: Message received: {}, payload: {}".format(self.device.name, msg.topic, msg.payload))

        stateList = [
            { 'key':'last_topic',   'value':  msg.topic},
            { 'key':'last_payload',   'value': msg.payload},
        ]
        self.device.updateStatesOnServer(stateList)
        indigo.activePlugin.triggerCheck(self.device)
