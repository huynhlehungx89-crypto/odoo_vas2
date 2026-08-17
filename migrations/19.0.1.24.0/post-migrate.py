# -*- coding: utf-8 -*-
"""R06 credit: partner_payable → receipt_counterpart; seed R10 nếu thiếu."""


def migrate(cr, version):
    from odoo import SUPERUSER_ID, api

    cr.execute("""
        UPDATE vas_rule_line AS l
           SET account_selector = 'receipt_counterpart'
          FROM vas_rule AS r
         WHERE l.rule_id = r.id
           AND r.code = 'R06'
           AND l.side = 'credit'
           AND l.account_selector = 'partner_payable'
    """)

    env = api.Environment(cr, SUPERUSER_ID, {})
    Rule = env['vas.rule']
    for regime in env['vas.regime'].search([('code', '=', 'TT133')]):
        if Rule.search([('regime_id', '=', regime.id), ('code', '=', 'R10')], limit=1):
            continue
        Rule.create({
            'code': 'R10',
            'name': 'Hàng mua đang đi đường (151)',
            'regime_id': regime.id,
            'event_type': 'goods_in_transit',
            'sequence': 49,
            'active': True,
            'line_ids': [
                (0, 0, {
                    'sequence': 10,
                    'side': 'debit',
                    'account_selector': 'goods_in_transit',
                    'amount_selector': 'untaxed',
                }),
                (0, 0, {
                    'sequence': 20,
                    'side': 'credit',
                    'account_selector': 'partner_payable',
                    'amount_selector': 'untaxed',
                }),
            ],
        })
