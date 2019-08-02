# MQTT

Plugin for the Indigo Home Automation system.

This plugin acts as a client to one or more MQTT brokers.

## Quick Start

1. Install Plugin
2. Create a Broker device
3. Enter Hostname or IP address, port, protocol, and transport for broker in config dialog
4. Subscribe to topics using Menu commands, Actions, or Scripts.
5. Set up triggers for received messages
6. Publish messages using Actions or Scripts.

## Scripting Examples

**PluginID**: com.flyingdiver.indigoplugin.mqtt

Subscribe to a topic.  'deviceId' is the plugin MQTT Broker device.

```
mqttPlugin = indigo.server.getPlugin("com.flyingdiver.indigoplugin.mqtt")
if mqttPlugin.isEnabled():
    props = {
    	'topic':"/indigo/alerts", 
    	'qos': 0
    }
    mqttPlugin.executeAction("add_subscription", deviceId=12345678, props=props)
```

Publish a message (payload) to a topic.  'deviceId' is the plugin MQTT Broker device.

```
mqttPlugin = indigo.server.getPlugin("com.flyingdiver.indigoplugin.mqtt")
if mqttPlugin.isEnabled():
    props = {
    	'topic':"/indigo/alerts", 
    	'payload': "alert=Fire", 
    	'qos': 0, 
    	'retain': False
    }
    mqttPlugin.executeAction("publish", deviceId=12345678, props=props)

```

Publish an Indigo device status to a topic.  'deviceId' is the plugin MQTT Broker device.  The device key in the props dictionary is the ID of the Indigo device to be published.

```
mqttPlugin = indigo.server.getPlugin("com.flyingdiver.indigoplugin.mqtt")
if mqttPlugin.isEnabled():
    props = {
    	'topic':"/indigo/alerts", 
    	'device': "9876543", 
    	'qos': 0, 
    	'retain': False
    }
    mqttPlugin.executeAction("publish_device", deviceId=12345678, props=props)

```
Unsubscribe from a topic.  'deviceId' is the plugin MQTT Broker device.

```
mqttPlugin = indigo.server.getPlugin("com.flyingdiver.indigoplugin.mqtt")
if mqttPlugin.isEnabled():
    props = {
    	'topic':"/indigo/alerts"
    }
    mqttPlugin.executeAction("del_subscription", deviceId=12345678, props=props)


```

Unsubscribe from all topics.  'deviceId' is the plugin MQTT Broker device.

```
mqttPlugin = indigo.server.getPlugin("com.flyingdiver.indigoplugin.mqtt")
if mqttPlugin.isEnabled():
    props = {}
    mqttPlugin.executeAction("clear_subscriptions", deviceId=12345678, props=props)


```

### Indigo 7 Only

This plugin requires Indigo 7 or greater.

