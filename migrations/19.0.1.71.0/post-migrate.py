# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Gỡ folder Cuối kỳ rỗng sau khi chuyển Kết chuyển sang Nghiệp vụ."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    menu = env.ref('connecta_vas.menu_vas_period_end', raise_if_not_found=False)
    if menu:
        menu.unlink()
