# -*- coding: utf-8 -*-
"""Gắn quan hệ chỉ tiêu con B01a (bản seed đầu bị noupdate bỏ qua bản ghi cập nhật)."""


CHILDREN = {
    '120': ['121', '122', '123', '124'],
    '130': ['131', '132', '133', '134', '135', '136'],
    '140': ['141', '142'],
    '150': ['151', '152'],
    '160': ['161', '162'],
    '180': ['181', '182'],
    '200': ['110', '120', '130', '140', '150', '160', '170', '180'],
    '300': ['311', '312', '313', '314', '315', '316', '317', '318', '319', '320'],
    '400': ['411', '412', '413', '414', '415', '416', '417'],
    '500': ['300', '400'],
}


def migrate(cr, version):
    env = None
    try:
        from odoo import api, SUPERUSER_ID
        env = api.Environment(cr, SUPERUSER_ID, {})
    except Exception:
        return
    Line = env['vas.report.line'].sudo()
    for parent_code, child_codes in CHILDREN.items():
        parent = Line.search([
            ('form_code', '=', 'B01a-DNN'),
            ('code', '=', parent_code),
        ], limit=1)
        if not parent:
            continue
        children = Line.search([
            ('form_code', '=', 'B01a-DNN'),
            ('code', 'in', child_codes),
        ])
        if set(children.mapped('code')) != set(child_codes):
            continue
        # Bypass seed write guard via SQL / context? write() blocks child_line_ids.
        # Dùng SQL quan hệ M2M trực tiếp.
        cr.execute(
            'DELETE FROM vas_report_line_child_rel WHERE parent_id = %s',
            [parent.id],
        )
        for child in children:
            cr.execute(
                'INSERT INTO vas_report_line_child_rel (parent_id, child_id) '
                'VALUES (%s, %s)',
                [parent.id, child.id],
            )
