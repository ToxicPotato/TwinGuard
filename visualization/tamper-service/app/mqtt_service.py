"""MQTT subscribe-transform-publish relay."""

from __future__ import annotations

import json
import logging
import threading

import paho.mqtt.client as mqtt

from .attack_controller import AttackController
from .config import Settings
from .rules import TamperRules

log = logging.getLogger(__name__)


class MqttTamperService:
    """Relay messages from one MQTT topic tree to another with optional tampering."""

    def __init__(self, settings: Settings, rules: TamperRules, controller: AttackController):
        self._settings = settings
        self._rules = rules
        self._controller = controller
        self._input_topic = f"{settings.input_prefix}/#"
        self._control_topic = f"{settings.control_topic_prefix}/#"
        self._client = mqtt.Client()
        if settings.mqtt_username:
            self._client.username_pw_set(settings.mqtt_username, settings.mqtt_password)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message

    def _on_connect(self, client, userdata, flags, rc):
        log.info(
            "Connected to MQTT broker (rc=%s); subscribing to %s and %s",
            rc,
            self._input_topic,
            self._control_topic,
        )
        client.subscribe(self._input_topic)
        client.subscribe(self._control_topic)

    def _on_message(self, client, userdata, msg):
        if msg.topic.startswith(f"{self._settings.control_topic_prefix}/"):
            self._handle_control_message(client, msg)
            return

        mapped = self._map_output_topic(msg.topic)
        if mapped is None:
            log.debug("Skipping unmapped topic: %s", msg.topic)
            return

        robot_id, suffix, output_topic = mapped
        payload = msg.payload.decode("utf-8", errors="strict").strip()
        transformed = self._rules.transform(robot_id, suffix, payload)
        info = client.publish(output_topic, transformed, qos=msg.qos, retain=msg.retain)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            log.warning("Publish failed for %s (rc=%s)", output_topic, info.rc)
            return

        if transformed != payload:
            log.warning("Tampered %s -> %s: raw=%r tampered=%r", msg.topic, output_topic, payload, transformed)
        else:
            log.debug("Relayed %s -> %s", msg.topic, output_topic)

    def _handle_control_message(self, client, msg) -> None:
        action = msg.topic.removeprefix(f"{self._settings.control_topic_prefix}/").strip("/")
        payload_text = msg.payload.decode("utf-8", errors="replace").strip()

        if action == "false_brake":
            try:
                duration_s = float(payload_text)
            except ValueError:
                log.warning("Invalid false-brake duration payload %r on %s", payload_text, msg.topic)
                return
            try:
                self._controller.trigger_false_brake(duration_s, None, 0.0)
            except ValueError as exc:
                log.warning("Rejected false-brake trigger on %s: %s", msg.topic, exc)
                return
            log.info("False-brake injection enabled for %.3f seconds via MQTT control topic", duration_s)
            return

        if action == "slowdown":
            try:
                speed_text, duration_text = _parse_pair_payload(payload_text)
                speed_mps = float(speed_text)
                duration_s = float(duration_text)
            except ValueError as exc:
                log.warning("Invalid slowdown payload %r on %s: %s", payload_text, msg.topic, exc)
                return
            try:
                self._rules.trigger_slowdown(speed_mps, duration_s)
            except ValueError as exc:
                log.warning("Rejected slowdown trigger on %s: %s", msg.topic, exc)
                return
            log.info(
                "Slowdown injection enabled at %.3f m/s for %.3f seconds via MQTT control topic",
                speed_mps,
                duration_s,
            )
            return

        if action == "reset":
            self._controller.reset()
            log.info("Tamper state reset via MQTT control topic")
            return

        if action == "status":
            status = self._controller.get_status()
            body = json.dumps(status, separators=(",", ":"))
            client.publish(
                f"{self._settings.control_topic_prefix}/status/response",
                body,
                qos=0,
                retain=False,
            )
            log.info("Scenario status published: %s", body)
            return

        log.warning("Unknown control action on %s", msg.topic)

    def _map_output_topic(self, topic: str) -> tuple[str, str, str] | None:
        prefix = self._settings.input_prefix
        if not topic.startswith(prefix + "/"):
            return None
        remainder = topic[len(prefix) + 1:]  # strip "prefix/"
        slash = remainder.find("/")
        if slash == -1:
            return None  # no suffix segment — not a robot signal topic
        robot_id = remainder[:slash]
        suffix = remainder[slash + 1:]
        output_topic = f"{self._settings.output_prefix}/{robot_id}/{suffix}"
        return robot_id, suffix, output_topic

    def reconnect(self, host: str, port: int, username: str | None, password: str | None, input_prefix: str | None = None) -> None:
        # Build the new client and wait for a CONNACK before touching the live session.
        # connect() only proves TCP — credential/ACL rejections arrive in the callback.
        connack_event = threading.Event()
        connack_rc: list[int] = []

        def _probe(client, userdata, flags, rc):
            connack_rc.append(rc)
            connack_event.set()

        new_client = mqtt.Client()
        if username:
            new_client.username_pw_set(username, password or None)
        new_client.on_connect = _probe
        new_client.on_message = self._on_message
        new_client.connect(host, port)  # raises on DNS/network error; old client untouched
        new_client.loop_start()

        if not connack_event.wait(timeout=5.0) or connack_rc[0] != 0:
            new_client.loop_stop()
            new_client.disconnect()
            rc_val = connack_rc[0] if connack_rc else None
            raise RuntimeError(
                f"Broker rejected connection (rc={rc_val})" if rc_val is not None else "Connection timed out"
            )

        # CONNACK accepted — update prefix if changed, retire old client first to avoid
        # a window where both clients consume the same topics and duplicate relayed messages.
        if input_prefix is not None:
            self._settings.input_prefix = input_prefix.strip("/") or self._settings.input_prefix
            self._input_topic = f"{self._settings.input_prefix}/#"

        self._client.loop_stop()
        self._client.disconnect()

        new_client.on_connect = self._on_connect
        new_client.subscribe(self._input_topic)
        new_client.subscribe(self._control_topic)

        self._client = new_client
        self._settings.mqtt_host = host
        self._settings.mqtt_port = port
        self._settings.mqtt_username = username or None
        self._settings.mqtt_password = password or None
        log.info("Tamper relay reconnected to %s:%s (input_prefix=%s)", host, port, self._settings.input_prefix)

    def start(self) -> None:
        log.info(
            "Starting tamper relay: %s/# -> %s/# (mode=%s, target_robot=%s)",
            self._settings.input_prefix,
            self._settings.output_prefix,
            self._settings.mode,
            self._settings.target_robot_id or "*",
        )
        try:
            # connect_async() registers the target without blocking; loop_start()
            # performs the actual handshake and retries automatically on transient failures.
            self._client.connect_async(self._settings.mqtt_host, self._settings.mqtt_port)
        except Exception as exc:
            log.warning(
                "Initial MQTT connect to %s:%s failed (%s); loop will keep retrying",
                self._settings.mqtt_host, self._settings.mqtt_port, exc,
            )
        self._client.loop_start()

    def stop(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()


def _parse_pair_payload(payload_text: str) -> tuple[str, str]:
    normalized = payload_text.replace(",", " ").split()
    if len(normalized) != 2:
        raise ValueError("expected '<speed_mps> <duration_s>'")
    return normalized[0], normalized[1]
