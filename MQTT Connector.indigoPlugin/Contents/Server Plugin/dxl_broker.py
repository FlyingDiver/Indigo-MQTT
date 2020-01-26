#! /usr/bin/env python
# -*- coding: utf-8 -*-
####################

import time
import logging
import indigo

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
            self.broker.logger.threaddebug(u"{}: Message {} ({}), received: {}, payload: {}".format(self.broker.device.name, event.message_id, event.message_type, event.destination_topic, event.payload))

            stateList = [
                { 'key':'last_topic',   'value': event.destination_topic   },
                { 'key':'last_payload', 'value': event.payload }
            ]
            self.broker.device.updateStatesOnServer(stateList)
            indigo.activePlugin.triggerCheck(self.broker.device)


    def __init__(self, device):
        self.logger = logging.getLogger("Plugin.DXLBroker")
        self.device = device
    
        address = device.pluginProps.get(u'address', "")
        port = device.pluginProps.get(u'port', "")
        ca_bundle = indigo.server.getInstallFolderPath() + '/' + device.pluginProps.get(u'ca_bundle', "")
        cert_file = indigo.server.getInstallFolderPath() + '/' + device.pluginProps.get(u'cert_file', "")
        private_key = indigo.server.getInstallFolderPath() + '/' + device.pluginProps.get(u'private_key', "")
        
        self.logger.debug(u"{}: Broker __init__ address = {}, ca_bundle = {}, cert_file = {}, private_key = {}".format(device.name, address, ca_bundle, cert_file, private_key))
        
        self.device.updateStateOnServer(key="status", value="Not Connected")
        self.device.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)

        # Create the client configuration
        broker = Broker.parse("ssl://{}:{}".format(address, port))
        config = DxlClientConfig(broker_ca_bundle=ca_bundle, cert_file=cert_file, private_key=private_key, brokers=[broker])
 
        # Create the DXL client
        self.dxl_client = DxlClient(config)   

        # Connect to the fabric
        self.dxl_client.connect()    
        self.device.updateStateOnServer(key="status", value="Connected")
        self.device.updateStateImageOnServer(indigo.kStateImageSel.SensorOn)            

        subs = self.device.pluginProps.get(u'subscriptions', None)
        if subs:
            for topic in subs:
                self.dxl_client.add_event_callback(topic, self.MyEventCallback(self))
                self.logger.info(u"{}: Subscribing to: {}".format(self.device.name, topic))
                
            
    def __del__(self):
        self.dxl_client.disconnect()        
        self.dxl_client.destroy()        
        self.device.updateStateOnServer(key="status", value="Not Connected")
        self.device.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)      
      
    def loop(self):
        pass
            
    def publish(self, topic, payload=None, qos=0, retain=False):
        event = Event(topic)
        event.payload = payload
        self.dxl_client.send_event(event)


    def subscribe(self, topic):
        self.logger.info(u"{}: Subscribing to: {}".format(self.device.name, topic))
        self.dxl_client.add_event_callback(topic, self.MyEventCallback(self))

    def unsubscribe(self, topic):
        self.logger.info(u"{}: Unsubscribing from: {}".format(self.device.name, topic))
        self.dxl_client.unsubscribe(topic)

    def refreshFromServer(self):
        self.device.refreshFromServer()

