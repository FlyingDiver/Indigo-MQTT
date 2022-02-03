#! /usr/bin/env python
# -*- coding: utf-8 -*-
####################

import time
import logging
import indigo
from os.path import exists

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

        self.username = device.pluginProps.get(u'username', None).strip()
        self.password = device.pluginProps.get(u'password', None).strip()

        self.logger.debug(f"{device.name}: Broker __init__ address = {self.address}, port = {self.port}, protocol = {self.protocol}, transport = {self.transport}")

        device.updateStateOnServer(key="status", value="Not Connected")
        device.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)

        self.client = mqtt.Client(client_id="indigo-mqtt-{}".format(device.id), clean_session=True, userdata=None, protocol=self.protocol, transport=self.transport)
        self.client.suppress_exceptions = True

        if bool(indigo.activePlugin.pluginPrefs[u"showDebugInfo"]):
            self.logger.debug(f"{device.name}: Enabling library level debugging")
            self.client.enable_logger(self.logger)

        if self.username:
            self.client.username_pw_set(self.username, self.password)

        if device.pluginProps.get('useTLS', False):

            certFile = device.pluginProps.get(u'certFile', None)
            if not certFile or not len(certFile):
                self.logger.debug(f"{device.name}: No cert file provided, using default cert_file")
                self.client.tls_set()
            else:
                self.logger.debug(u"{}: Specified cert_file '{}'".format(device.name, certFile))
                if certFile[0:1] != '/':  # leave absolute path alone
                    certFile = f"{indigo.server.getInstallFolderPath()}/{certFile}"
                if not exists(certFile):
                    self.logger.debug(f"{device.name}: Specified cert file '{certFile}' doesn't exist, using default cert_file")
                    self.client.tls_set()
                else:
                    self.logger.debug(f"{device.name}: Using cert_file '{certFile}'")
                    self.client.tls_set(ca_certs=certFile)

        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message
        self.client.on_publish = self.on_publish
        self.client.on_subscribe = self.on_subscribe
        self.client.on_unsubscribe = self.on_unsubscribe

        try:
            self.client.connect(self.address, self.port, 60)
        except Exception as e:
            self.logger.debug(f"{device.name}: Broker connect error: {e}")
            device.updateStateOnServer(key="status", value="Connection Failed")
            device.updateStateImageOnServer(indigo.kStateImageSel.SensorTripped)
            self.connected = False
        else:
            self.connected = True
            self.client.loop_start()

    def disconnect(self):
        self.client.on_disconnect = None
        device = indigo.devices[self.deviceID]
        self.logger.info(f"{device.name}: Disconnecting")
        self.client.loop_stop()
        self.client.disconnect()
        device.updateStateOnServer(key="status", value="Not Connected")
        device.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)

    def publish(self, topic, payload=None, qos=0, retain=False):
        self.client.publish(topic, payload, qos, retain)

    def subscribe(self, topic, qos=0):
        device = indigo.devices[self.deviceID]
        self.logger.info(f"{device.name}: Subscribing to: {topic} ({qos})")
        self.client.subscribe(topic, qos)

    def unsubscribe(self, topic):
        device = indigo.devices[self.deviceID]
        self.logger.info(f"{device.name}: Unsubscribing from: {topic}")
        self.client.unsubscribe(topic)

    ################################################################################
    # Callbacks
    ################################################################################

    def on_connect(self, client, userdata, flags, rc):
        device = indigo.devices[self.deviceID]
        self.logger.debug(f"{device.name}: Connected with result code {rc}")

        # Subscribing in on_connect() means that if we lose the connection and reconnect then subscriptions will be renewed.
        subs = device.pluginProps.get('subscriptions', None)
        if subs:
            for s in subs:
                qos = int(s[0:1])
                topic = s[2:]
                self.logger.info(f"{device.name}: Subscribing to: {topic} ({qos})")
                client.subscribe(topic, qos)

        device.updateStateOnServer(key="status", value="Connected {}".format(rc))
        device.updateStateImageOnServer(indigo.kStateImageSel.SensorOn)

    def on_disconnect(self, client, userdata, rc):
        device = indigo.devices[self.deviceID]
        self.logger.error(f"{device.name}: Disconnected with result code {rc}")
        device.updateStateOnServer(key="status", value="Disconnected {}".format(rc))
        device.updateStateImageOnServer(indigo.kStateImageSel.SensorTripped)
        self.connected = False

    def on_message(self, client, userdata, msg):
        device = indigo.devices[self.deviceID]
        payload = msg.payload.decode("utf-8")
        self.logger.threaddebug(f"{device.name}: Message topic: {msg.topic}, payload = {payload}")
        indigo.activePlugin.processReceivedMessage(self.deviceID, msg.topic, payload)

    def on_publish(self, client, userdata, mid):
        device = indigo.devices[self.deviceID]
        self.logger.threaddebug(f"{device.name}: Message published: {mid}")

    def on_subscribe(self, client, userdata, mid, granted_qos):
        device = indigo.devices[self.deviceID]
        self.logger.threaddebug(f"{device.name}: Subscribe complete: {mid}, {granted_qos}")

    def on_unsubscribe(self, client, userdata, mid):
        device = indigo.devices[self.deviceID]
        self.logger.threaddebug(f"{device.name}: Unsubscribe complete: {mid}")
