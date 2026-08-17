# -*- coding: utf-8 -*-
"""R25 credit: partner_payable → landed_counterpart (nhánh thuế NK)."""


def migrate(cr, version):
    cr.execute("""
        UPDATE vas_rule_line AS l
           SET account_selector = 'landed_counterpart'
          FROM vas_rule AS r
         WHERE l.rule_id = r.id
           AND r.code = 'R25'
           AND l.side = 'credit'
           AND l.account_selector = 'partner_payable'
    """)
