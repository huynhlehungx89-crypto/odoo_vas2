# -*- coding: utf-8 -*-
"""Kéo lại menu Nghiệp vụ VN sang Accounting (Enterprise).

Nguyên nhân lệch: XML menuitem parent=account.menu_finance; mỗi lần -u trước
khi bọc noupdate đã đè parent về Invoicing rỗng → menu biến mất khỏi Accounting.
"""
from odoo import SUPERUSER_ID, api

from odoo.addons.connecta_vas.hooks import _reparent_vn_operations_menu


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    _reparent_vn_operations_menu(env)
