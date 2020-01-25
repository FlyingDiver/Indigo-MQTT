#! /usr/bin/env python
# -*- coding: utf-8 -*-
####################

import time
import logging
import indigo

import paho.mqtt.client as mqtt

################################################################################
class MQTTBroker(object):

    def __init__(self, device):
        self.logger = logging.getLogger("Plugin.Broker")
        self.device = device
        self.reconnectTime = None
    
        self.address = device.pluginProps.get(u'address', "")
        self.port = int(device.pluginProps.get(u'port', 1883))
        self.protocol = int(device.pluginProps.get(u'protocol', 4))
        self.transport = device.pluginProps.get(u'transport', "tcp")

        self.username = device.pluginProps.get(u'username', None)
        self.password = device.pluginProps.get(u'password', None)

        self.useTLS = device.pluginProps.get(u'useTLS', False)

        self.loopTimeout = float(device.pluginProps.get(u'loopTimeout', '0.5'))

        self.logger.debug(u"{}: Broker __init__ address = {}, port = {}, protocol = {}, transport = {}, timeout = {}".format(device.name, self.address, self.port, self.protocol, self.transport, self.loopTimeout))
        
        self.device.updateStateOnServer(key="status", value="Not Connected")
        self.device.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)

        self.client = mqtt.Client(client_id="indigo-mqtt-{}".format(device.id), clean_session=True, userdata=None, protocol=self.protocol, transport=self.transport)

        if bool(indigo.activePlugin.pluginPrefs[u"showDebugInfo"]):
            self.logger.debug(u"{}: Enabling library level debugging".format(self.device.name))    
            self.client.enable_logger(self.logger)

        if self.username:
            self.client.username_pw_set(self.username, self.password)
        
        if self.useTLS:
            self.client.tls_set()
    
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message
        self.client.on_publish = self.on_publish
        self.client.on_subscribe = self.on_subscribe
        self.client.on_unsubscribe = self.on_unsubscribe

        try:
            self.client.connect(self.address, self.port, 60)
        except:
            self.device.updateStateOnServer(key="status", value="Connection Failed")
            self.device.updateStateImageOnServer(indigo.kStateImageSel.SensorTripped)
            self.connected = False
            self.reconnectDelay = 5.0
            self.reconnectTime = time.time() + self.reconnectDelay
        else:
            self.connected = True
            
    def __del__(self):
        self.client.disconnect()
        self.device.updateStateOnServer(key="status", value="Not Connected")
        self.device.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)      
      
    def loop(self):
        if self.connected:
            self.client.loop(timeout=0.5)
        elif self.reconnectTime and (time.time() > self.reconnectTime):
            self.logger.debug(u"{}: Attempting reconnect".format(self.device.name))
            try:
                self.client.connect(self.address, self.port, 60)
            except:
                if self.reconnectDelay < 300.0:
                    self.reconnectDelay = self.reconnectDelay * 2.0
                self.reconnectTime = time.time() + self.reconnectDelay
            else:
                self.connected = True
            
    def publish(self, topic, payload=None, qos=0, retain=False):
        self.client.publish(topic, payload, qos, retain)

    def subscribe(self, topic, qos=0):
        self.logger.info(u"{}: Subscribing to: {} ({})".format(self.device.name, topic, qos))
        self.client.subscribe(topic, qos)

    def unsubscribe(self, topic):
        self.logger.info(u"{}: Unsubscribing from: {}".format(self.device.name, topic))
        self.client.unsubscribe(topic)

    def refreshFromServer(self):
        self.device.refreshFromServer()
        

    ################################################################################
    # Callbacks
    ################################################################################

    def on_connect(self, client, userdata, flags, rc):
        self.logger.debug(u"{}: Connected with result code {}".format(self.device.name, rc))
        self.device.refreshFromServer()

        # Subscribing in on_connect() means that if we lose the connection and reconnect then subscriptions will be renewed.
        subs = self.device.pluginProps.get(u'subscriptions', None)
        if subs:
            for s in subs:
                qos = int(s[0:1])
                topic = s[2:]
                client.subscribe(topic, qos)
                self.logger.info(u"{}: Subscribing to: {} ({})".format(self.device.name, topic, qos))
            
        self.device.updateStateOnServer(key="status", value="Connected {}".format(rc))
        self.device.updateStateImageOnServer(indigo.kStateImageSel.SensorOn)

    def on_disconnect(self, client, userdata, rc):
        self.logger.error(u"{}: Disconnected with result code {}".format(self.device.name, rc))
        self.device.updateStateOnServer(key="status", value="Disconnected {}".format(rc))
        self.device.updateStateImageOnServer(indigo.kStateImageSel.SensorTripped)
        self.connected = False
        self.reconnectDelay = 1.0
        self.reconnectTime = time.time() + self.reconnectDelay

    def on_message(self, client, userdata, msg):
        self.logger.threaddebug(u"{}: Message received: {}, payload: {}".format(self.device.name, msg.topic, msg.payload))

        stateList = [
            { 'key':'last_topic',   'value': msg.topic   },
            { 'key':'last_payload', 'value': msg.payload }
        ]
        self.device.updateStatesOnServer(stateList)
        indigo.activePlugin.triggerCheck(self.device)

    def on_publish(self, client, userdata, mid):
        self.logger.threaddebug(u"{}: Message published: {}".format(self.device.name, mid))

    def on_subscribe(self, client, userdata, mid, granted_qos):
        self.logger.threaddebug(u"{}: Subscribe complete: {}, {}".format(self.device.name, mid, granted_qos))

    def on_unsubscribe(self, client, userdata, mid):
        self.logger.threaddebug(u"{}: Unsubscribe complete: {}".format(self.device.name, mid))

