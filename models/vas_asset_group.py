# -*- coding: utf-8 -*-
from odoo import fields, models


class VasAssetGroup(models.Model):
    """Nhóm TSCĐ theo Phụ lục 1 TT45 (khung thời gian min–max năm)."""

    _name = 'vas.asset.group'
    _description = 'Nhóm TSCĐ TT45 Phụ lục 1'
    _order = 'code, id'

    code = fields.Char(required=True, index=True)
    name = fields.Char(required=True)
    parent_id = fields.Many2one(
        'vas.asset.group', string='Nhóm cha', index=True, ondelete='cascade',
    )
    child_ids = fields.One2many('vas.asset.group', 'parent_id', string='Nhóm con')
    min_years = fields.Float(string='Thời gian KH tối thiểu (năm)')
    max_years = fields.Float(string='Thời gian KH tối đa (năm)')
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('code_uniq', 'unique(code)', 'Mã nhóm TSCĐ phải duy nhất.'),
    ]
