# -*- coding: utf-8 -*-
import logging

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class VasPayrollDepartmentMap(models.Model):
    _name = 'vas.payroll.department.map'
    _description = 'Map bộ phận → TK chi phí lương (154/6421/6422)'
    _order = 'department_id, id'

    company_id = fields.Many2one(
        'res.company', required=True, index=True,
        default=lambda self: self.env.company,
    )
    department_id = fields.Many2one(
        'hr.department', string='Bộ phận', required=True, index=True,
        ondelete='cascade',
    )
    expense_account_id = fields.Many2one(
        'vas.account', string='TK chi phí', required=True,
        ondelete='restrict',
        help='154 (SX) / 6421 (bán hàng) / 6422 (QLDN).',
    )
    cost_item_id = fields.Many2one(
        'vas.cost.item',
        string='Khoản mục chi phí',
        ondelete='restrict',
        help='W12: chỉ nhận khoản mục lá (không nút tổng hợp, không CPD).',
    )

    _sql_constraints = [
        (
            'dept_company_uniq',
            'unique(department_id, company_id)',
            'Mỗi bộ phận chỉ map một TK chi phí trong công ty.',
        ),
    ]

    @api.constrains('cost_item_id')
    def _check_cost_item_leaf_not_cpd(self):
        for row in self:
            item = row.cost_item_id
            if not item:
                continue
            if item.is_aggregate_node:
                raise ValidationError(_(
                    'Map bộ phận lương chỉ nhận khoản mục lá. '
                    '«%(code)s — %(name)s» là nút tổng hợp.',
                    code=item.code or '',
                    name=item.name or '',
                ))
            if item._is_cpd_seed():
                raise ValidationError(_(
                    'Không được khai khoản mục «Chưa phân loại» (CPD) trên '
                    'map bộ phận lương. CPD chỉ dùng khi máy tra không ra.'
                ))

    @api.model
    def resolve_expense_account(self, company, department, fallbacks=None):
        """Trả vas.account CP; mặc định 6422 nếu chưa map.

        Rơi về mặc định thì ghi vào ``fallbacks`` (nhãn BỘ PHẬN) — đúng khuôn
        ``vas.sync._product_account``: KHÔNG raise (một bộ phận chưa khai
        không được dừng cả lượt đồng bộ §8.3), nhưng cũng KHÔNG im lặng —
        caller gắn cờ ``vas_has_default_account`` lên bút toán qua
        ``_default_account_flag_vals`` để lọc được và chặn khóa kỳ.
        """
        Sync = self.env['vas.sync']
        regime = company.vas_regime_id
        if department:
            mapping = self.search([
                ('company_id', '=', company.id),
                ('department_id', '=', department.id),
            ], limit=1)
            if mapping:
                return mapping.expense_account_id
        dept_label = (
            department.display_name if department else _('(không có bộ phận)')
        )
        _logger.warning(
            'VAS payroll: bộ phận %s chưa khai map TK chi phí lương '
            '→ dùng mặc định 6422', dept_label,
        )
        if fallbacks is not None:
            fallbacks.append({
                'selector': 'payroll_expense',
                'default_code': '6422',
                'label': _(
                    'bộ phận %(department)s → dùng mặc định 6422 '
                    '(chưa khai Map bộ phận lương)',
                    department=dept_label,
                ),
            })
        return Sync._account_by_code(regime, '6422')

    @api.model
    def resolve_cost_item(self, company, department, fallbacks=None):
        """Trả vas.cost.item; chưa map → CPD + ghi fallbacks (cờ unclassified)."""
        CostItem = self.env['vas.cost.item']
        if department:
            mapping = self.search([
                ('company_id', '=', company.id),
                ('department_id', '=', department.id),
            ], limit=1)
            if mapping and mapping.cost_item_id:
                return mapping.cost_item_id
        dept_label = (
            department.display_name if department else _('(không có bộ phận)')
        )
        _logger.warning(
            'VAS payroll: bộ phận %s chưa khai khoản mục chi phí '
            '→ dùng CPD Chưa phân loại', dept_label,
        )
        cpd = CostItem._system_by_code(company, 'CPD')
        if fallbacks is not None:
            fallbacks.append({
                'source': 'payroll',
                'label': _(
                    'bộ phận %(department)s → khoản mục Chưa phân loại (CPD)',
                    department=dept_label,
                ),
            })
        return cpd
