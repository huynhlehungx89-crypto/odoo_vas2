# -*- coding: utf-8 -*-
"""Kéo menu Nghiệp vụ VN sang app Accounting khi có module accountant."""
from odoo import SUPERUSER_ID, api

from odoo.addons.connecta_vas.hooks import _reparent_vn_operations_menu


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    _reparent_vn_operations_menu(env)
