"""Module-level singletons shared across routers."""

from __future__ import annotations

from .attack_controller import AttackController
from .config import settings
from .mqtt_service import MqttTamperService
from .rules import TamperRules

rules = TamperRules(settings)
controller = AttackController(settings, rules)
service = MqttTamperService(settings, rules, controller)
