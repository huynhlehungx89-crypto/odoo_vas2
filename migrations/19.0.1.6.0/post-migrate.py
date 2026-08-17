# -*- coding: utf-8 -*-
"""Gộp R19/R20/R21 về nhãn chung trên account.payment.

1. vas_is_employee_advance (Boolean) → vas_operation_type (Selection).
2. R20 đổi từ ghép cặp heuristic sang một payment + sổ đích: các dòng quy tắc
   `bank`/`cash` cố định phải thành `dest_bank_cash`/`bank_cash`. File dữ liệu
   W3 mang noupdate="1" nên bản ghi cũ không tự cập nhật — sửa tại đây.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

R20_LINE_SELECTORS = {
    'vas_rule_tt133_r20_l1': 'dest_bank_cash',
    'vas_rule_tt133_r20_l2': 'bank_cash',
}


def _migrate_operation_type(cr):
    cr.execute("""
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'account_payment'
           AND column_name = 'vas_is_employee_advance'
    """)
    if not cr.fetchone():
        return
    cr.execute("""
        UPDATE account_payment
           SET vas_operation_type = 'employee_advance'
         WHERE vas_is_employee_advance IS TRUE
           AND vas_operation_type IS NULL
    """)
    migrated = cr.rowcount
    cr.execute("ALTER TABLE account_payment DROP COLUMN vas_is_employee_advance")
    _logger.info(
        'connecta_vas: chuyen %s account.payment sang vas_operation_type=employee_advance',
        migrated,
    )


def _migrate_r20_rule_lines(env):
    for xmlid, selector in R20_LINE_SELECTORS.items():
        line = env.ref(f'connecta_vas.{xmlid}', raise_if_not_found=False)
        if line and line.account_selector != selector:
            line.account_selector = selector
            _logger.info('connecta_vas: R20 %s -> %s', xmlid, selector)


def migrate(cr, version):
    if not version:
        return
    _migrate_operation_type(cr)
    _migrate_r20_rule_lines(api.Environment(cr, SUPERUSER_ID, {}))
