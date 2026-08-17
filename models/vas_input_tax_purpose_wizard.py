# -*- coding: utf-8 -*-
"""Wizard sửa hàng loạt mục đích sử dụng thuế đầu vào."""
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class VasInputTaxPurposeWizard(models.TransientModel):
    _name = 'vas.input.tax.purpose.wizard'
    _description = 'Sửa hàng loạt mục đích sử dụng thuế đầu vào'

    use_purpose = fields.Selection(
        [
            ('taxable_only', 'Dùng riêng hoạt động chịu thuế'),
            ('exempt_only', 'Dùng riêng hoạt động không chịu thuế'),
            ('mixed', 'Dùng chung'),
            ('investment', 'Dự án đầu tư'),
            ('unset', 'Chưa xác định'),
        ],
        string='Mục đích sử dụng',
        required=True,
        default='taxable_only',
    )
    line_ids = fields.Many2many(
        'vas.move.line',
        string='Dòng thuế',
        required=True,
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_ids = self.env.context.get('active_ids') or []
        if active_ids and 'line_ids' in fields_list:
            res['line_ids'] = [(6, 0, active_ids)]
        return res

    def action_apply(self):
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_('Chưa chọn dòng thuế.'))
        companies = self.line_ids.mapped('move_id.company_id')
        if any(not c.vas_has_exempt_sales for c in companies):
            raise UserError(_(
                'Công ty chưa bật «Có bán hàng không chịu thuế» — '
                'không sửa mục đích sử dụng.'
            ))
        self.line_ids.write({'use_purpose': self.use_purpose})
        self.env['vas.move.line'].recompute_input_vat_deduction(lines=self.line_ids)
        return {'type': 'ir.actions.act_window_close'}
