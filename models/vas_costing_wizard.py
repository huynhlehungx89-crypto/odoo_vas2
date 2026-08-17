# -*- coding: utf-8 -*-
"""Wizard lý do từ chối / hoàn tác nhận — luồng nút màn hình Chặng 3."""
from odoo import _, fields, models
from odoo.exceptions import UserError


class VasCostingReasonWizard(models.TransientModel):
    _name = 'vas.costing.reason.wizard'
    _description = 'Nhập lý do từ chối hoặc hoàn tác nhận'

    period_id = fields.Many2one(
        'vas.costing.period', string='Kỳ', ondelete='cascade',
    )
    variance_sheet_id = fields.Many2one(
        'vas.variance.sheet', string='Phiếu vượt', ondelete='cascade',
    )
    action_kind = fields.Selection(
        [
            ('reject', 'Từ chối duyệt'),
            ('unreceive', 'Hoàn tác nhận phân bổ'),
            ('defer_unconfigured', 'Để lại kỳ sau (chưa cấu hình PB)'),
            ('variance_reverse', 'Đảo phiếu xử lý vượt định mức'),
        ],
        string='Hành động', required=True,
    )
    reason = fields.Text(string='Lý do', required=True)

    def action_confirm(self):
        self.ensure_one()
        if not (self.reason or '').strip():
            raise UserError(_('Bắt buộc nhập lý do.'))
        if self.action_kind == 'variance_reverse':
            sheet = self.variance_sheet_id
            if not sheet:
                raise UserError(_('Thiếu phiếu xử lý vượt để đảo.'))
            return sheet.action_reverse(reason=self.reason.strip())
        period = self.period_id
        if not period:
            raise UserError(_('Thiếu kỳ giá thành.'))
        if self.action_kind == 'reject':
            return period.action_reject(reason=self.reason.strip())
        if self.action_kind == 'unreceive':
            return period.action_unreceive_allocation(reason=self.reason.strip())
        if self.action_kind == 'defer_unconfigured':
            return period.action_confirm_defer_unconfigured(
                reason=self.reason.strip(),
            )
        raise UserError(_('Hành động không hợp lệ.'))


class VasCostingDeferLog(models.Model):
    _name = 'vas.costing.defer.log'
    _description = 'Nhật ký để lại khoản mục chưa cấu hình sang kỳ sau'
    _order = 'create_date desc, id desc'

    period_id = fields.Many2one(
        'vas.costing.period', string='Kỳ', required=True,
        index=True, ondelete='restrict',
    )
    reason = fields.Text(string='Lý do', required=True)
    snapshot = fields.Text(
        string='Ảnh chụp khoản mục / số dòng / số tiền', required=True,
    )
    user_id = fields.Many2one(
        'res.users', string='Người xác nhận', required=True,
        default=lambda self: self.env.user, ondelete='restrict',
    )
    company_id = fields.Many2one(
        related='period_id.company_id', store=True,
    )
