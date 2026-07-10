# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An Indigo Domotics plugin ("MQTT Connector") that acts as a client to one or more MQTT-family brokers,
letting Indigo devices/variables be published to and controlled from MQTT topics. It's not a standalone
Python app — it runs embedded inside the Indigo Server process, which supplies the `indigo` module at
runtime (there's no local `indigo` package to install; don't try to `pip install` or import-check it
outside Indigo).

Quick Start / user docs: https://github.com/FlyingDiver/Indigo-MQTT/wiki

## Repo layout

- `MQTT Connector.indigoPlugin/Contents/Info.plist` — plugin version, bundle ID, Indigo Server API version.
- `MQTT Connector.indigoPlugin/Contents/Server Plugin/` — all the actual Python code and Indigo XML config:
  - `plugin.py` — the `Plugin(indigo.PluginBase)` entry point. Owns device/variable subscriptions, topic
    trigger matching, device/variable publishing (via pystache templates), the message queue mechanism
    used by the `fetchQueuedMessage` action, and all the dynamic list/config-UI callback methods referenced
    from the XML files below.
  - `mqtt_broker.py` (`MQTTBroker`) — wraps `paho.mqtt.client` for standard MQTT brokers.
  - `aiot_broker.py` (`AIoTBroker`) — wraps `AWSIoTPythonSDK` for AWS IoT Core endpoints.
  - `dxl_broker.py` (`DXLBroker`) — wraps McAfee/OpenDXL's `dxlclient`. Imported lazily/optionally in
    `plugin.py` (`try: from dxl_broker import DXLBroker`) since the `dxlclient` dependency is not bundled
    (see commented-out line in `requirements.txt`) — a DXL broker device will fail gracefully if it's absent.
  - `subscription_format.py` — the single place the per-broker-type subscription string format is
    implemented (see the Architecture section for the three functions and who imports what); kept
    standalone so the broker modules can import it without a circular import through `plugin.py`.
  - `Devices.xml`, `Actions.xml`, `Events.xml`, `MenuItems.xml`, `PluginConfig.xml` — Indigo's declarative
    UI/config definitions. Field `method="..."` and callback attributes here map directly to method names
    on the `Plugin` class in `plugin.py` — when changing a callback's signature or name, update both sides.
  - `requirements.txt` — pinned third-party deps (`paho-mqtt`, `pystache`, `AWSIoTPythonSDK`); `dxlclient`
    is intentionally commented out.
  - `Packages/` — vendored copies of the above dependencies actually shipped inside the plugin bundle
    (this is what Indigo runs against, not requirements.txt directly).

## Architecture

There is one broker class instance per Indigo "broker" device (`mqttBroker`, `aIoTBroker`, or `dxlBroker`
device type), held in `Plugin.brokers`, keyed by Indigo device ID. `deviceStartComm`/`deviceStopComm` in
`plugin.py` create/tear down these broker objects as devices start/stop. Each broker class (`MQTTBroker`,
`AIoTBroker`, `DXLBroker`) exposes the same informal interface — `publish()`, `subscribe()`,
`unsubscribe()`, `disconnect()` — so `plugin.py` treats them interchangeably regardless of which
underlying client library is in use.

Inbound message flow: each broker's underlying client library invokes that broker's own callback
(`on_message` / `onMessage` / `MyEventCallback.on_event`) on receipt, which all funnel into
`Plugin.processReceivedMessage(devID, topic, payload)`. That single method handles:
- **Topic aggregation** (`self.aggregators`, persisted in `pluginPrefs["aggregators"]`) — merges messages
  under a common topic base into one nested JSON payload via `recurseAggregator`/`deep_merge_dicts`.
- **Device/variable control** — regex-matches the topic against `control_device_pattern` /
  `control_variable_pattern` from the broker device's props to turn on/off/toggle/set Indigo devices or
  variables.
- **Trigger dispatch** — iterates `self.triggers` (populated via `triggerStartProcessing`/
  `triggerStopProcessing`) and fires Indigo triggers for `messageReceived`, `stringMatch` (exact topic
  match), and `topicMatch` (segment-by-segment match list supporting `Match`/`Any`/`Skip`/`Regex`/`End`
  components, see the loop in `processReceivedMessage`). `topicMatch` triggers can also enqueue the message
  for later polling via `queueMessage`/`fetchQueuedMessageAction` (per-`message_type` `Queue`s in
  `self.message_queues`).

Outbound flow: `deviceUpdated`/`variableUpdated` (Indigo change-notification callbacks, subscribed to in
`startup()`) check each broker device's `published_devices`/`published_variables` lists, then render the
topic and payload using `pystache` templates (`device_template_topic`/`device_template_payload`, and the
variable equivalents) against a dict built by `make_dev_dict`/`make_var_dict`, and call `broker.publish()`.
Actions (`publishMessageAction`, `publishDeviceAction`, `addSubscriptionAction`, `delSubscriptionAction`)
in `Actions.xml`/`plugin.py` provide the same publish/subscribe operations as explicit Indigo actions.

Subscriptions are stored as URL-quoted strings in each broker device's `subscriptions` plugin prop list:
`qos:topic` for `mqttBroker`/`aIoTBroker` devices, and a bare quoted topic (no `qos:` prefix) for
`dxlBroker` devices. `subscription_format.py` is the single source of truth for this format:
`encode_subscription()` (only ever needed in `plugin.py`, since that's the only place new subscription
entries are constructed), `decode_subscription()` (returns `(qos, topic)`, `qos` is `None` for
`dxlBroker`), and `decode_subscription_topic()` (the common case — just the topic). Every place that
constructs or parses a subscription entry (in `plugin.py`, `mqtt_broker.py`, `aiot_broker.py`,
`dxl_broker.py`) goes through one of these three; don't hand-roll `urllib.parse.quote`/`unquote` at a
new call site. `validateDeviceConfigUi` diffs
`subscriptions` against `old_subscriptions` to incrementally subscribe/unsubscribe on the live broker
connection when a device's config is saved, and each broker re-subscribes everything from
`pluginProps['subscriptions']` on its own connect callback (so subscriptions survive reconnects).

## Working with this code

There is no build step, package manager, linter, or test suite in this repo — it's plain Python files
loaded directly by the Indigo Server plugin host. There's no way to run or exercise this code outside a
live Indigo installation with the plugin loaded, so changes are verified by installing/reloading the
plugin in Indigo and checking its event log (the `Plugin.logger` output, including `threaddebug`-level
messages when `showDebugInfo` is enabled in plugin prefs).

When adding a config field in `Devices.xml`/`Actions.xml`/`Events.xml`, add or update the corresponding
`pluginProps`/`props` reads and any list-generating callback method in `plugin.py` in the same change —
the XML and the Python are not independently useful.
