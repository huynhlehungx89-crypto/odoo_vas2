# -*- coding: utf-8 -*-
from odoo import fields, models


class VasFullReconcile(models.Model):
    _name = 'vas.full.reconcile'
    _description = 'Đối chiếu đầy đủ VAS'
    _order = 'id desc'

    name = fields.Char(string='Tên', required=True)
    reconciled_line_ids = fields.One2many(
        'vas.move.line', 'full_reconcile_id', string='Dòng đã khớp',
    )
