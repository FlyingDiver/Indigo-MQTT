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
        self.logger = logging.getLogger("Plugin.MQTTBroker")
        self.deviceID = device.id
        self.reconnectTime = None
    
        self.address = device.pluginProps.get(u'address', "")
        self.port = int(device.pluginProps.get(u'port', 1883))
        self.protocol = int(device.pluginProps.get(u'protocol', 4))
        self.transport = device.pluginProps.get(u'transport', "tcp")

        self.username = device.pluginProps.get(u'username', None)
        self.password = device.pluginProps.get(u'password', None)

        self.useTLS = device.pluginProps.get(u'useTLS', False)

        self.logger.debug(u"{}: Broker __init__ address = {}, port = {}, protocol = {}, transport = {}".format(device.name, self.address, self.port, self.protocol, self.transport))
        
        device.updateStateOnServer(key="status", value="Not Connected")
        device.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)

        self.client = mqtt.Client(client_id="indigo-mqtt-{}".format(device.id), clean_session=True, userdata=None, protocol=self.protocol, transport=self.transport)
        self.client.suppress_exceptions = True
        
        if bool(indigo.activePlugin.pluginPrefs[u"showDebugInfo"]):
            self.logger.debug(u"{}: Enabling library level debugging".format(device.name))    
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
            device.updateStateOnServer(key="status", value="Connection Failed")
            device.updateStateImageOnServer(indigo.kStateImageSel.SensorTripped)
            self.connected = False
        else:
            self.connected = True
            self.client.loop_start()
            
                  
    def disconnect(self):
        self.client.on_disconnect = None
        device = indigo.devices[self.deviceID]
        self.logger.info(u"{}: Disconnecting".format(device.name))
        self.client.loop_stop()
        self.client.disconnect()
        device.updateStateOnServer(key="status", value="Not Connected")
        device.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)  
        
        
    def publish(self, topic, payload=None, qos=0, retain=False):
        self.client.publish(topic, payload, qos, retain)

    def subscribe(self, topic, qos=0):
        device = indigo.devices[self.deviceID]
        self.logger.info(u"{}: Subscribing to: {} ({})".format(device.name, topic, qos))
        self.client.subscribe(topic, qos)

    def unsubscribe(self, topic):
        device = indigo.devices[self.deviceID]
        self.logger.info(u"{}: Unsubscribing from: {}".format(device.name, topic))
        self.client.unsubscribe(topic)


    ################################################################################
    # Callbacks
    ################################################################################

    def on_connect(self, client, userdata, flags, rc):
        device = indigo.devices[self.deviceID]
        self.logger.debug(u"{}: Connected with result code {}".format(device.name, rc))

        # Subscribing in on_connect() means that if we lose the connection and reconnect then subscriptions will be renewed.
        subs = device.pluginProps.get(u'subscriptions', None)
        if subs:
            for s in subs:
                qos = int(s[0:1])
                topic = s[2:]
                self.logger.info(u"{}: Subscribing to: {} ({})".format(device.name, topic, qos))
                client.subscribe(topic, qos)
            
        device.updateStateOnServer(key="status", value="Connected {}".format(rc))
        device.updateStateImageOnServer(indigo.kStateImageSel.SensorOn)

    def on_disconnect(self, client, userdata, rc):
        device = indigo.devices[self.deviceID]
        self.logger.error(u"{}: Disconnected with result code {}".format(device.name, rc))
        device.updateStateOnServer(key="status", value="Disconnected {}".format(rc))
        device.updateStateImageOnServer(indigo.kStateImageSel.SensorTripped)
        self.connected = False

    def on_message(self, client, userdata, msg):
        device = indigo.devices[self.deviceID]
        payload = msg.payload.decode("utf-8")
        self.logger.threaddebug(u"{}: Message topic: {}, payload = {}".format(device.name, msg.topic, payload))
        indigo.activePlugin.processReceivedMessage(self.deviceID, msg.topic, payload)

    def on_publish(self, client, userdata, mid):
        device = indigo.devices[self.deviceID]
        self.logger.threaddebug(u"{}: Message published: {}".format(device.name, mid))

    def on_subscribe(self, client, userdata, mid, granted_qos):
        device = indigo.devices[self.deviceID]
        self.logger.threaddebug(u"{}: Subscribe complete: {}, {}".format(device.name, mid, granted_qos))

    def on_unsubscribe(self, client, userdata, mid):
        device = indigo.devices[self.deviceID]
        self.logger.threaddebug(u"{}: Unsubscribe complete: {}".format(device.name, mid))

