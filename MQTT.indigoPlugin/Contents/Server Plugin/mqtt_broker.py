#! /usr/bin/env python
# -*- coding: utf-8 -*-
####################

import time
import socket
import json
import logging
import requests
import threading
import indigo

################################################################################
class Broker(object):

    def __init__(self, device):
        self.logger = logging.getLogger("Plugin.Broker")
        self.device = device
        
        self.address = device.pluginProps.get(u'address', "")
        self.http_port = int(device.pluginProps.get(u'port', 1883))

        self.logger.debug(u"Broker __init__ address = {}, port = {}".format(self.address, self.http_port))
        
            
    def __del__(self):
        stateList = [
            { 'key':'status',   'value':  "Disconnected"},
        ]
        self.device.updateStatesOnServer(stateList)
        self.device.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)
        
