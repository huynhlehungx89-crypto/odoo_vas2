# -*- coding: utf-8 -*-
"""Trục 1 — chọn tài khoản động theo sản phẩm.

1. Các dòng quy tắc đang cắm cứng 5111/632 chuyển sang selector tra theo sản phẩm.
   File dữ liệu W1/W4 mang noupdate="1" nên bản ghi cũ không tự cập nhật.
2. Bảng ánh xạ dời từ 3 trường trên product.category / product.template sang model
   `vas.account.map`. Giá trị kế toán đã khai TAY phải được CHUYỂN, không mất, và
   THẮNG dòng seed mặc định. Xong mới DROP cột cũ.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

PRODUCT_SELECTOR_LINES = {
    'vas_rule_tt133_r01_l2': 'product_revenue',
    'vas_rule_tt133_r02_l1': 'product_cogs',
    'vas_rule_tt133_r03_l1': 'product_revenue',
    'vas_rule_tt133_r04_l1': 'product_revenue',
}

# cột cũ → trường trên vas.account.map
COLUMN_TO_FIELD = {
    'vas_stock_account_id': 'stock_account_id',
    'vas_revenue_account_id': 'revenue_account_id',
    'vas_cogs_account_id': 'cogs_account_id',
}

LEGACY_TABLES = {
    'product_category': ('category', 'category_id'),
    'product_template': ('product', 'product_id'),
}


def _migrate_rule_lines(env):
    for xmlid, selector in PRODUCT_SELECTOR_LINES.items():
        line = env.ref(f'connecta_vas.{xmlid}', raise_if_not_found=False)
        if not line or line.account_selector == selector:
            continue
        line.write({'account_selector': selector, 'account_id': False})
        _logger.info('connecta_vas: %s -> %s', xmlid, selector)


def _legacy_columns(cr, table):
    cr.execute(
        """
        SELECT column_name FROM information_schema.columns
         WHERE table_name = %s AND column_name IN %s
        """,
        (table, tuple(COLUMN_TO_FIELD)),
    )
    return [row[0] for row in cr.fetchall()]


def _map_targets(env):
    """(regime, company_id) sẽ nhận dòng ánh xạ chuyển đổi.

    Một công ty có chế độ → dòng dùng chung (company_id trống, như seed).
    Nhiều công ty → mỗi công ty một dòng để không trộn chế độ.
    """
    companies = env['res.company'].search([('vas_regime_id', '!=', False)])
    if not companies:
        return []
    if len(companies) == 1:
        return [(companies.vas_regime_id, False)]
    return [(company.vas_regime_id, company.id) for company in companies]


def _convert_table(env, table, apply_to, key_field):
    cr = env.cr
    columns = _legacy_columns(cr, table)
    if not columns:
        return 0
    cr.execute(
        f"SELECT id, {', '.join(columns)} FROM {table} "
        f"WHERE {' OR '.join(f'{c} IS NOT NULL' for c in columns)}"
    )
    rows = cr.fetchall()
    Map = env['vas.account.map']
    converted = 0
    for regime, company_id in _map_targets(env):
        for row in rows:
            record_id, values = row[0], row[1:]
            vals = {
                COLUMN_TO_FIELD[column]: value
                for column, value in zip(columns, values)
                if value
            }
            if not vals:
                continue
            existing = Map.search([
                ('regime_id', '=', regime.id),
                ('apply_to', '=', apply_to),
                (key_field, '=', record_id),
                ('company_id', '=', company_id),
            ], limit=1)
            if existing:
                # Giá trị khai tay thắng seed mặc định.
                existing.write(vals)
            else:
                Map.create({
                    'regime_id': regime.id,
                    'apply_to': apply_to,
                    key_field: record_id,
                    'company_id': company_id,
                    **vals,
                })
            converted += 1
            _logger.info(
                'connecta_vas: chuyen %s(%s) -> vas.account.map %s',
                table, record_id, vals,
            )
    for column in columns:
        cr.execute(f'ALTER TABLE {table} DROP COLUMN {column}')
    _logger.info('connecta_vas: drop %s cot cu tren %s', len(columns), table)
    return converted


def _migrate_account_map(env):
    total = 0
    for table, (apply_to, key_field) in LEGACY_TABLES.items():
        total += _convert_table(env, table, apply_to, key_field)
    _logger.info('connecta_vas: tong cong %s dong vas.account.map tu bang cu', total)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    _migrate_rule_lines(env)
    _migrate_account_map(env)
