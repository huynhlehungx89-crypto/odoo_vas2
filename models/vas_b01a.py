# -*- coding: utf-8 -*-
"""Wizard lập B01a → lưu vas.report.snapshot. Xem lại = đọc bản đã lưu."""
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class VasB01aWizard(models.TransientModel):
    _name = 'vas.b01a.wizard'
    _description = 'Lập bảng cân đối kế toán VAS (B01a-DNN)'

    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
    )
    regime_id = fields.Many2one(related='company_id.vas_regime_id', store=True)
    period_from_id = fields.Many2one(
        'vas.period', string='Từ kỳ', required=True, ondelete='cascade',
    )
    period_to_id = fields.Many2one(
        'vas.period', string='Đến kỳ', required=True, ondelete='cascade',
    )
    hide_reversed = fields.Boolean(
        string='Ẩn đã đảo/điều chỉnh',
        default=True,
    )

    def action_generate(self):
        """Lập bản mới (tính một lần) rồi mở form bản đã lưu."""
        self.ensure_one()
        snap = self.env['vas.report.snapshot'].generate_b01a(
            self.company_id,
            self.period_from_id,
            self.period_to_id,
            hide_reversed=self.hide_reversed,
        )
        return self.env['vas.report.engine'].action_open_fs_client(snap)

    @api.model
    def get_report_data(self, options):
        """Tương thích cũ / test: nếu có snapshot_id → chỉ đọc; không thì lập mới rồi đọc.

        Mở lại bản đã lưu phải truyền ``snapshot_id`` — không tính lại.
        """
        options = options or {}
        snap_id = options.get('snapshot_id')
        if snap_id:
            snap = self.env['vas.report.snapshot'].browse(snap_id)
            if not snap.exists():
                raise UserError(_('Không tìm thấy bản báo cáo đã lưu.'))
            return snap.get_report_data()

        company = self.env['res.company'].browse(
            options.get('company_id') or self.env.company.id
        )
        period_from = self.env['vas.period'].browse(options.get('period_from_id'))
        period_to = self.env['vas.period'].browse(options.get('period_to_id'))
        if not period_from or not period_to:
            raise UserError(_('Chọn Từ kỳ và Đến kỳ trước khi lập báo cáo.'))
        snap = self.env['vas.report.snapshot'].generate_b01a(
            company, period_from, period_to,
            hide_reversed=bool(options.get('hide_reversed', True)),
        )
        return snap.get_report_data()

    @api.model
    def action_export_xlsx_options(self, options):
        return self.env['vas.report.engine'].action_export_xlsx_fs(
            options, 'B01a-DNN',
        )

    @api.model
    def action_export_pdf_options(self, options):
        return self.env['vas.report.engine'].action_export_pdf_fs(
            options, 'B01a-DNN',
        )
