# -*- coding: utf-8 -*-
"""Seed R09b — chiết khấu/giảm giá mua (phi kho) cho DB đã cài (noupdate XML)."""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Regime = env['vas.regime']
    Rule = env['vas.rule']
    for regime in Regime.search([('code', '=', 'TT133')]):
        if Rule.search([('regime_id', '=', regime.id), ('code', '=', 'R09b')], limit=1):
            continue
        Rule.create({
            'code': 'R09b',
            'name': 'Chiết khấu/giảm giá mua (phi kho)',
            'regime_id': regime.id,
            'event_type': 'purchase_discount',
            'sequence': 53,
            'active': True,
            'line_ids': [
                (0, 0, {
                    'sequence': 10,
                    'side': 'debit',
                    'account_selector': 'partner_payable',
                    'amount_selector': 'total',
                }),
                (0, 0, {
                    'sequence': 20,
                    'side': 'credit',
                    'account_selector': 'product_inventory',
                    'amount_selector': 'untaxed',
                }),
                (0, 0, {
                    'sequence': 30,
                    'side': 'credit',
                    'account_selector': 'tax_input',
                    'amount_selector': 'tax',
                }),
            ],
        })
        _logger.info('connecta_vas 1.98: created R09b for regime %s', regime.code)
