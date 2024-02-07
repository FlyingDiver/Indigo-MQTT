#! /usr/bin/env python
# -*- coding: utf-8 -*-
####################

import time
import logging
import indigo
import urllib.parse

from dxlclient.client import DxlClient
from dxlclient.client_config import DxlClientConfig
from dxlclient.callbacks import EventCallback
from dxlclient.broker import Broker
from dxlclient.message import Event


################################################################################
class DXLBroker(object):

    class MyEventCallback(EventCallback):
        def __init__(self, broker):
            EventCallback.__init__(self)
            self.broker = broker

        def on_event(self, event):
            self.broker.logger.threaddebug(
                f"{self.broker.device.name}: Message {event.message_id} ({event.message_type}), received: {event.destination_topic}, payload: {event.payload}")
            indigo.activePlugin.processReceivedMessage(self.broker.device.id, event.destination_topic, event.payload)

    def __init__(self, device):
        self.logger = logging.getLogger("Plugin.DXLBroker")
        self.deviceID = device.id
    
        address = device.pluginProps.get(u'address', "")
        port = device.pluginProps.get(u'port', "")
        ca_bundle = indigo.server.getInstallFolderPath() + '/' + device.pluginProps.get(u'ca_bundle', "")
        cert_file = indigo.server.getInstallFolderPath() + '/' + device.pluginProps.get(u'cert_file', "")
        private_key = indigo.server.getInstallFolderPath() + '/' + device.pluginProps.get(u'private_key', "")
        
        self.logger.debug(f"{device.name}: Broker __init__ address = {address}, ca_bundle = {ca_bundle}, cert_file = {cert_file}, private_key = {private_key}")
        
        device.updateStateOnServer(key="status", value="Not Connected")
        device.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)

        # Create the client configuration
        broker = Broker.parse(f"ssl://{address}:{port}")
        config = DxlClientConfig(broker_ca_bundle=ca_bundle, cert_file=cert_file, private_key=private_key, brokers=[broker])
 
        # Create the DXL client
        self.dxl_client = DxlClient(config)   

        # Connect to the fabric
        self.dxl_client.connect()    
        device.updateStateOnServer(key="status", value="Connected")
        device.updateStateImageOnServer(indigo.kStateImageSel.SensorOn)            

        if subs := device.pluginProps.get('subscriptions'):
            for sub in subs:
                s = urllib.parse.unquote(sub)
                self.dxl_client.add_event_callback(s, self.MyEventCallback(self))
                self.logger.info(f"{device.name}: Subscribing to: {s}")
            
    def disconnect(self):
        device = indigo.devices[self.deviceID]
        self.dxl_client.disconnect()        
        self.dxl_client.destroy()        
        device.updateStateOnServer(key="status", value="Not Connected")
        device.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)      
      
    def publish(self, topic, payload=None, qos=0, retain=False):
        event = Event(topic)
        event.payload = payload
        self.dxl_client.send_event(event)

    def subscribe(self, topic):
        device = indigo.devices[self.deviceID]
        self.logger.info(f"{device.name}: Subscribing to: {topic}")
        self.dxl_client.add_event_callback(topic, self.MyEventCallback(self))

    def unsubscribe(self, topic):
        device = indigo.devices[self.deviceID]
        self.logger.info(f"{device.name}: Unsubscribing from: {topic}")
        self.dxl_client.unsubscribe(topic)
