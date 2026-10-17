"""Isolated GGSO engine. The executable v1 profile is TEST_ONLY, never production.

GeoMobiNet, the legacy controller, DB state, and pricing publication are untouched.
"""
SCHEMA_VERSION = "ggso.decision.v1"
SEMANTIC_PROFILE = "ggso.confirmed-bookings.eligible-idle.h5.test.v1"
