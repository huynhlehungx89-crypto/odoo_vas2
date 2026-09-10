# -*- coding: utf-8 -*-
from odoo import fields, models, _


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    vas_regime_id = fields.Many2one(
        related='company_id.vas_regime_id',
        readonly=False,
        string='Chế độ kế toán VAS',
    )
    vas_start_date = fields.Date(
        related='company_id.vas_start_date',
        readonly=False,
        string='Ngày bắt đầu ghi sổ VAS',
    )
    vas_theo_doi_hang_di_duong = fields.Boolean(
        related='company_id.vas_theo_doi_hang_di_duong',
        readonly=False,
        string='Theo dõi hàng đi đường (TK 151)',
    )
    vas_boc_tach_khau_hao_htk = fields.Boolean(
        related='company_id.vas_boc_tach_khau_hao_htk',
        readonly=False,
        string='Bóc tách được số khấu hao nằm trong hàng tồn kho',
    )
    vas_khau_hao_trong_htk = fields.Float(
        related='company_id.vas_khau_hao_trong_htk',
        readonly=False,
        string='Số khấu hao nằm trong HTK cuối kỳ',
        digits=(16, 2),
    )
    vas_has_exempt_sales = fields.Boolean(
        related='company_id.vas_has_exempt_sales',
        readonly=False,
        string='Có bán hàng không chịu thuế GTGT',
    )
    vas_pos_cash_account_id = fields.Many2one(
        related='company_id.vas_pos_cash_account_id',
        readonly=False,
        string='TK quỹ nộp tiền quầy',
    )
    vas_scrap_account_id = fields.Many2one(
        related='company_id.vas_scrap_account_id',
        readonly=False,
        string='TK đối ứng hủy hàng',
    )
    vas_vietqr_bank_bin = fields.Char(
        related='company_id.vas_vietqr_bank_bin',
        readonly=False,
        string='BIN ngân hàng (VietQR)',
    )
    vas_vietqr_account_no = fields.Char(
        related='company_id.vas_vietqr_account_no',
        readonly=False,
        string='Số TK nhận VietQR',
    )
    vas_vietqr_account_name = fields.Char(
        related='company_id.vas_vietqr_account_name',
        readonly=False,
        string='Tên TK nhận VietQR',
    )
    vas_payment_113_stale_days = fields.Integer(
        related='company_id.vas_payment_113_stale_days',
        readonly=False,
        string='Cảnh báo treo 113 (ngày)',
    )

    def action_vas_sync_now(self):
        self.ensure_one()
        stats = self.env['vas.sync'].sync_company(self.company_id)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Đồng bộ VAS'),
                'message': str(stats),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            },
        }
