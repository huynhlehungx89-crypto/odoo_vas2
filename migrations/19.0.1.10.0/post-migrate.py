# -*- coding: utf-8 -*-
"""Bỏ R13 — điều chuyển kho nội bộ không ghi bút toán nữa.

Xem KE_HOACH_ENGINE_RULE.md §5.10c. Migration này chỉ xóa ĐỊNH NGHĨA rule; bút
toán R13 đã sinh thì **liệt kê ra log và GIỮ NGUYÊN** — xóa sổ kế toán là việc
của kế toán, không phải của script nâng cấp.

Xóa cả rule do người dùng tự tạo với `event_type='stock_transfer'`, vì giá trị
đó đã bị gỡ khỏi selection và sẽ thành dữ liệu mồ côi.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

R13_REFS = ('Điều chuyển kho nội bộ',)


def _report_r13_moves(env):
    """In ra bút toán R13 cũ để kế toán tự quyết, KHÔNG xóa."""
    cr = env.cr
    cr.execute(
        """
        SELECT m.id, m.name, m.date, m.company_id, m.source_res_id,
               COALESCE(SUM(l.debit), 0)
          FROM vas_move m
          LEFT JOIN vas_move_line l ON l.move_id = m.id
         WHERE m.source_model = 'stock.move' AND m.ref IN %s
         GROUP BY m.id, m.name, m.date, m.company_id, m.source_res_id
         ORDER BY m.id
        """,
        (R13_REFS,),
    )
    rows = cr.fetchall()
    if not rows:
        _logger.info('connecta_vas: khong co but toan R13 cu tren DB nay')
        return
    _logger.warning(
        'connecta_vas: CON %s but toan R13 (dieu chuyen kho noi bo) tren so VAS. '
        'GIU NGUYEN - ke toan tu quyet dao hay de lai. Danh sach:', len(rows),
    )
    for move_id, name, date, company_id, src, debit in rows:
        _logger.warning(
            'connecta_vas:   vas.move id=%s %s ngay=%s company=%s stock.move=%s tong_no=%s',
            move_id, name, date, company_id, src, debit,
        )


def _drop_r13_rules(env):
    cr = env.cr
    cr.execute("SELECT id, code, name FROM vas_rule WHERE event_type = 'stock_transfer'")
    rules = cr.fetchall()
    if not rules:
        _logger.info('connecta_vas: khong con vas.rule nao event_type=stock_transfer')
        return
    ids = tuple(r[0] for r in rules)
    for rule_id, code, name in rules:
        _logger.info('connecta_vas: xoa vas.rule id=%s %s %r', rule_id, code, name)
    cr.execute("DELETE FROM vas_rule_line WHERE rule_id IN %s", (ids,))
    _logger.info('connecta_vas: xoa %s dong vas.rule.line', cr.rowcount)
    cr.execute("DELETE FROM vas_rule WHERE id IN %s", (ids,))
    _logger.info('connecta_vas: xoa %s vas.rule', cr.rowcount)
    cr.execute(
        """
        DELETE FROM ir_model_data
         WHERE module = 'connecta_vas'
           AND ((model = 'vas.rule' AND res_id IN %s)
                OR name IN ('vas_rule_tt133_r13_l1', 'vas_rule_tt133_r13_l2'))
        """,
        (ids,),
    )


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    _report_r13_moves(env)
    _drop_r13_rules(env)
