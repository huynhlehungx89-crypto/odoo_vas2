# -*- coding: utf-8 -*-
"""Siết R19c/R19d/R19e + bảo đảm R19g có mặt trên DB đã cài.

File W6 không mang noupdate="1" nên -u thường tự cập nhật; migration này là
lưới an toàn khi bản ghi rule đã bị người dùng chỉnh hoặc noupdate bị bật tay.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

UPDATES = {
    'connecta_vas.vas_rule_tt133_r19c': (
        '[("payment_mode", "=", "own_account"), ("vas_advance_payment_id", "!=", False)]'
    ),
    'connecta_vas.vas_rule_tt133_r19d': (
        '[("payment_mode", "=", "own_account"), ("vas_advance_payment_id", "=", False)]'
    ),
    'connecta_vas.vas_rule_tt133_r19e': (
        '[("payment_type", "=", "inbound")]'
    ),
}


def _patch_conditions(env):
    for xmlid, condition in UPDATES.items():
        rule = env.ref(xmlid, raise_if_not_found=False)
        if not rule:
            _logger.warning('connecta_vas: thieu %s — bo qua', xmlid)
            continue
        if rule.condition != condition:
            _logger.info(
                'connecta_vas: %s condition %r -> %r',
                rule.code, rule.condition, condition,
            )
            rule.condition = condition


def _ensure_r19g(env):
    rule = env.ref('connecta_vas.vas_rule_tt133_r19g', raise_if_not_found=False)
    if rule:
        _logger.info('connecta_vas: R19g da co (id=%s)', rule.id)
        return
    # XML chua nap (truong hop hiem) — tao toi thieu de engine khong silent-skip.
    regime = env.ref('connecta_vas.vas_regime_tt133', raise_if_not_found=False)
    if not regime:
        _logger.warning('connecta_vas: thieu regime TT133, khong tao duoc R19g')
        return
    existing = env['vas.rule'].search([
        ('regime_id', '=', regime.id), ('code', '=', 'R19g'),
    ], limit=1)
    if existing:
        _logger.info('connecta_vas: R19g ton tai khong xmlid (id=%s)', existing.id)
        return
    _logger.warning(
        'connecta_vas: R19g chua co sau khi -u — kiem tra data/vas_rule_tt133_w6.xml',
    )


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    _patch_conditions(env)
    _ensure_r19g(env)
