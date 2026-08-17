# -*- coding: utf-8 -*-
"""TRỤC 2 — tài khoản chi phí.

1. R08 bỏ hardcode 6421 → selector `product_expense`. File W4 mang noupdate="1"
   nên bản ghi cũ KHÔNG tự cập nhật, phải sửa ở đây.
2. R08 đổi `move_kind` từ `purchase_inv` sang `expense`. Bút toán R08 đã sinh
   trước đây vẫn mang kind cũ; không đổi thì lần đồng bộ tới `_already_synced`
   tra không thấy và sẽ ghi TRÙNG trên cùng hóa đơn.

Cột `expense_account_id` do ORM tự thêm — không cần DDL ở đây.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

OLD_R08_ACCOUNT_CODE = '6421'


def _migrate_r08_rule_line(env):
    line = env.ref('connecta_vas.vas_rule_tt133_r08_l1', raise_if_not_found=False)
    if not line:
        _logger.warning('connecta_vas: khong tim thay R08 line 1, bo qua')
        return
    _logger.info(
        'connecta_vas: R08 line TRUOC selector=%s account=%s',
        line.account_selector, line.account_id.code or '(trong)',
    )
    if line.account_selector != 'product_expense':
        line.write({'account_selector': 'product_expense', 'account_id': False})
    _logger.info(
        'connecta_vas: R08 line SAU  selector=%s account=%s',
        line.account_selector, line.account_id.code or '(trong)',
    )

    rule = env.ref('connecta_vas.vas_rule_tt133_r08', raise_if_not_found=False)
    # W4 mang noupdate="1" nên tên cũ không tự đổi; đổi ở đây bất kể mã hóa
    # thế nào (DB seed / DB thật đều về cùng một tên chuẩn).
    if rule and rule.name != 'Chi phí mua ngoài':
        _logger.info('connecta_vas: R08 doi ten %r -> Chi phí mua ngoài', rule.name)
        rule.name = 'Chi phí mua ngoài'


def _migrate_r08_move_kind(env):
    """Bút toán R08 cũ: purchase_inv → expense.

    Nhận diện bằng chính `ref` của bút toán (engine ghi `rule.name` vào đó) nên
    không phụ thuộc chuỗi cứng: lấy tên rule từ DB, kể cả tên đã đổi ở bước trên.
    """
    cr = env.cr
    names = ['Mua dịch vụ', 'Chi phí mua ngoài']
    rule = env.ref('connecta_vas.vas_rule_tt133_r08', raise_if_not_found=False)
    if rule and rule.name not in names:
        names.append(rule.name)
    cr.execute(
        """
        SELECT move_kind, count(*) FROM vas_move
         WHERE source_model = 'account.move' AND ref IN %s
         GROUP BY move_kind
        """,
        (tuple(names),),
    )
    _logger.info('connecta_vas: but toan R08 TRUOC = %s', cr.fetchall())
    cr.execute(
        """
        UPDATE vas_move SET move_kind = 'expense'
         WHERE source_model = 'account.move'
           AND move_kind = 'purchase_inv'
           AND ref IN %s
        """,
        (tuple(names),),
    )
    changed = cr.rowcount
    cr.execute(
        """
        SELECT move_kind, count(*) FROM vas_move
         WHERE source_model = 'account.move' AND ref IN %s
         GROUP BY move_kind
        """,
        (tuple(names),),
    )
    _logger.info(
        'connecta_vas: but toan R08 SAU = %s (doi %s dong)', cr.fetchall(), changed,
    )


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    _migrate_r08_move_kind(env)
    _migrate_r08_rule_line(env)
