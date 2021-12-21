#! /usr/bin/env python
# -*- coding: utf-8 -*-
####################

import json
import time
import indigo

mqttPlugin = indigo.server.getPlugin("com.flyingdiver.indigoplugin.mqtt")
if mqttPlugin.isEnabled():
    props = {
        'message_type':"#Test#" 
    }
    while True:
        message_data = mqttPlugin.executeAction("fetchQueuedMessage", deviceId=1867973662, props=props, waitUntilDone=True)
        if message_data != None:
            indigo.server.log("Queue Fetch, version = {}, message_type = {}, topic_parts = {}".format(message_data["version"], message_data["message_type"], message_data["topic_parts"]))
            device_data = json.loads(message_data["payload"])
            indigo.server.log("Queue Fetch, device_data = {}".format(device_data))
        else:
            time.sleep(1.0)