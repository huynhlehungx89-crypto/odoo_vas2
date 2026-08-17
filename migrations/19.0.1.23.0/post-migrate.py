# -*- coding: utf-8 -*-
"""Seed R27 (nộp GTGT hàng NK) nếu DB chưa có."""


def migrate(cr, version):
    from odoo import SUPERUSER_ID, api

    env = api.Environment(cr, SUPERUSER_ID, {})
    Rule = env['vas.rule']
    for regime in env['vas.regime'].search([('code', '=', 'TT133')]):
        if Rule.search([('regime_id', '=', regime.id), ('code', '=', 'R27')], limit=1):
            continue
        Rule.create({
            'code': 'R27',
            'name': 'M11-7 · Nợ 33312 / Có 111|112 · TT133 Điều 41',
            'regime_id': regime.id,
            'event_type': 'import_vat_payment',
            'condition': (
                '[("vas_operation_type", "=", "import_vat_payment"), '
                '("payment_type", "=", "outbound")]'
            ),
            'sequence': 61,
            'active': True,
            'line_ids': [
                (0, 0, {
                    'sequence': 10,
                    'side': 'debit',
                    'account_selector': 'tax_import_vat_payable',
                    'amount_selector': 'paid',
                }),
                (0, 0, {
                    'sequence': 20,
                    'side': 'credit',
                    'account_selector': 'bank_cash',
                    'amount_selector': 'paid',
                }),
            ],
        })
