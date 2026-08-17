# -*- coding: utf-8 -*-
"""Wizard lập B09 → lưu vas.report.snapshot (từ bản B01a/B02 đã lập)."""
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class VasB09Wizard(models.TransientModel):
    _name = 'vas.b09.wizard'
    _description = 'Lập bản thuyết minh BCTC VAS (B09-DNN)'

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
    copy_prior_year = fields.Boolean(
        string='Chép nội dung người điền từ năm trước (nếu kỳ này trống)',
        default=True,
        help='Nội dung chép sang được đánh dấu «năm trước — cần rà lại».',
    )

    def action_generate(self):
        self.ensure_one()
        snap = self.env['vas.report.snapshot'].generate_b09(
            self.company_id,
            self.period_from_id,
            self.period_to_id,
            hide_reversed=self.hide_reversed,
            copy_prior_year=self.copy_prior_year,
        )
        return self.env['vas.report.engine'].action_open_fs_client(snap)

    @api.model
    def get_report_data(self, options):
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
        snap = self.env['vas.report.snapshot'].generate_b09(
            company, period_from, period_to,
            hide_reversed=bool(options.get('hide_reversed', True)),
        )
        return snap.get_report_data()

    @api.model
    def action_export_xlsx_options(self, options):
        return self.env['vas.report.engine'].action_export_xlsx_fs(
            options, 'B09-DNN',
        )

    @api.model
    def action_export_pdf_options(self, options):
        return self.env['vas.report.engine'].action_export_pdf_fs(
            options, 'B09-DNN',
        )
