#! /usr/bin/env python
# -*- coding: utf-8 -*-
####################

import urllib.parse

# DXL subscriptions are stored as a bare quoted topic; mqtt/aIoT subscriptions are stored
# as a quoted "qos:topic" string. These two helpers are the single place that format is
# encoded/decoded, instead of every call site re-deriving it.


def encode_subscription(deviceTypeId, topic, qos=0):
    if deviceTypeId == 'dxlBroker':
        return urllib.parse.quote(topic)
    return urllib.parse.quote(f"{qos}:{topic}")


def decode_subscription(deviceTypeId, entry):
    s = urllib.parse.unquote(entry)
    if deviceTypeId == 'dxlBroker':
        return None, s
    return int(s[0:1]), s[2:]
