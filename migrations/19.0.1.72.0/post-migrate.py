# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Lượt 2: nhóm ready + gỡ 7 mục Giá thành khỏi Cấu hình (noupdate seed)."""
    env = api.Environment(cr, SUPERUSER_ID, {'vas_ops_allow_write': True})

    group_vals = {
        'vas_ops_group_bank': {'state': 'ready', 'screen_kind': 'hub', 'temp_action_xmlid': False},
        'vas_ops_group_purchase': {
            'state': 'ready', 'screen_kind': 'workflow', 'temp_action_xmlid': False,
        },
        'vas_ops_group_sale': {
            'state': 'ready', 'screen_kind': 'workflow', 'temp_action_xmlid': False,
        },
        'vas_ops_group_stock': {'state': 'ready', 'screen_kind': 'hub', 'temp_action_xmlid': False},
        'vas_ops_group_costing': {
            'state': 'ready', 'screen_kind': 'workflow', 'temp_action_xmlid': False,
        },
    }
    for xmlid, vals in group_vals.items():
        rec = env.ref('connecta_vas.%s' % xmlid, raise_if_not_found=False)
        if rec:
            rec.write(vals)

    for xmlid in (
        'menu_vas_opening_wip',
        'menu_vas_closing_wip',
        'menu_vas_costing_period',
        'menu_vas_allocation_run',
        'menu_vas_variance_sheet',
        'menu_vas_cost_item',
        'menu_vas_cost_object',
    ):
        menu = env.ref('connecta_vas.%s' % xmlid, raise_if_not_found=False)
        if menu:
            menu.unlink()
