# -*- coding: utf-8 -*-
"""Đổi tên danh mục NQ 204 hết nhãn OCR; gỡ menu thuế đã chuyển chỗ."""
import importlib.util
import logging
from pathlib import Path

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

_STALE_MENUS = (
    'menu_vas_gtgt_listing',
    'menu_vas_tax_deduction_rule_under_tax',
    'menu_vas_input_tax_lines_under_tax',
    'menu_vas_input_tax_lines',
)


def _names():
    path = Path(__file__).with_name('exclusion_display_names.py')
    spec = importlib.util.spec_from_file_location(
        'vas_excl_display_names', path,
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.display_name


def migrate(cr, version):
    display_name = _names()
    env = api.Environment(cr, SUPERUSER_ID, {})
    Excl = env['vas.gtgt.reduction.exclusion'].with_context(active_test=False)
    n_fix = n_und = 0
    for rec in Excl.search([]):
        new = display_name(rec.code, rec.code_kind, rec.name or '')
        if new != rec.name:
            rec.name = new
            n_fix += 1
        if (new or '').startswith('Chưa xác định'):
            n_und += 1
    _logger.info(
        'connecta_vas 1.90: exclusion names updated=%s undetermined=%s',
        n_fix, n_und,
    )
    Menu = env['ir.ui.menu']
    Data = env['ir.model.data']
    for xmlid in _STALE_MENUS:
        data = Data.search([
            ('module', '=', 'connecta_vas'),
            ('name', '=', xmlid),
        ], limit=1)
        if not data:
            continue
        menu = Menu.browse(data.res_id).exists()
        if menu:
            menu.unlink()
        data.unlink()


_logger = logging.getLogger(__name__)

_STALE_MENUS = (
    'menu_vas_gtgt_listing',
    'menu_vas_tax_deduction_rule_under_tax',
    'menu_vas_input_tax_lines_under_tax',
    'menu_vas_input_tax_lines',
)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Excl = env['vas.gtgt.reduction.exclusion'].with_context(active_test=False)
    n_fix = n_und = 0
    for rec in Excl.search([]):
        new = display_name(rec.code, rec.code_kind, rec.name or '')
        if new != rec.name:
            rec.name = new
            n_fix += 1
        if (new or '').startswith('Chưa xác định'):
            n_und += 1
    _logger.info(
        'connecta_vas 1.90: exclusion names updated=%s undetermined=%s',
        n_fix, n_und,
    )
    Menu = env['ir.ui.menu']
    Data = env['ir.model.data']
    for xmlid in _STALE_MENUS:
        data = Data.search([
            ('module', '=', 'connecta_vas'),
            ('name', '=', xmlid),
        ], limit=1)
        if not data:
            continue
        menu = Menu.browse(data.res_id).exists()
        if menu:
            menu.unlink()
        data.unlink()
