# -*- coding: utf-8 -*-
"""W12 Chặng 6 — Phiếu xử lý vượt định mức / sai hỏng NVL.

Hệ thống gợi ý, kế toán xác nhận. Đường một chiều qua 154.
Không hard-depend mrp.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare, float_is_zero


TREATMENT_TYPES = [
    ('pending', 'Chờ xác minh'),
    ('claim', 'Phải thu bồi thường'),
    ('payroll', 'Khấu trừ lương'),
    ('writeoff', 'Không thu hồi được'),
]


class VasVarianceAccountConfig(models.Model):
    _name = 'vas.variance.account.config'
    _description = 'Cấu hình TK xử lý vượt định mức'
    _order = 'company_id, regime_id, id'

    company_id = fields.Many2one(
        'res.company', required=True, index=True, ondelete='restrict',
        default=lambda self: self.env.company,
    )
    regime_id = fields.Many2one(
        'vas.regime', required=True, index=True, ondelete='restrict',
        default=lambda self: self.env.company.vas_regime_id,
    )
    account_pending_id = fields.Many2one(
        'vas.account', string='TK chờ xác minh', ondelete='restrict',
        help='Đề xuất 1381 — kế toán chọn lại được.',
    )
    account_claim_id = fields.Many2one(
        'vas.account', string='TK phải thu bồi thường', ondelete='restrict',
        help='Đề xuất 1388.',
    )
    account_payroll_id = fields.Many2one(
        'vas.account', string='TK khấu trừ lương', ondelete='restrict',
        help='Đề xuất 334.',
    )
    account_writeoff_id = fields.Many2one(
        'vas.account', string='TK không thu hồi được', ondelete='restrict',
        help='Đề xuất 632.',
    )
    active = fields.Boolean(default=True)

    _company_regime_uniq = models.Constraint(
        'UNIQUE(company_id, regime_id)',
        'Mỗi công ty / chế độ chỉ một dòng cấu hình xử lý vượt.',
    )

    @api.model
    def _get_for(self, company, regime):
        return self.search([
            ('company_id', '=', company.id),
            ('regime_id', '=', regime.id),
            ('active', '=', True),
        ], limit=1)

    def _account_for_type(self, treatment_type):
        self.ensure_one()
        return {
            'pending': self.account_pending_id,
            'claim': self.account_claim_id,
            'payroll': self.account_payroll_id,
            'writeoff': self.account_writeoff_id,
        }.get(treatment_type)

    @api.model
    def _seed_defaults_tt133(self):
        """Gợi ý TK từ danh mục TT133 — chỉ tạo khi đủ mã; không đoán mã gần."""
        regime = self.env.ref('connecta_vas.vas_regime_tt133', raise_if_not_found=False)
        if not regime:
            return True
        codes = {
            '1381': 'account_pending_id',
            '1388': 'account_claim_id',
            '334': 'account_payroll_id',
            '632': 'account_writeoff_id',
        }
        Acc = self.env['vas.account']
        found = {}
        missing = []
        for code, field in codes.items():
            acc = Acc.search([('regime_id', '=', regime.id), ('code', '=', code)], limit=1)
            if not acc:
                missing.append(code)
            else:
                found[field] = acc.id
        if missing:
            # Không tự thay mã gần — dừng seed, để kế toán cấu hình tay
            return True
        for company in self.env['res.company'].search([]):
            if not company.vas_regime_id or company.vas_regime_id != regime:
                continue
            existing = self._get_for(company, regime)
            if existing:
                continue
            self.create({
                'company_id': company.id,
                'regime_id': regime.id,
                **found,
            })
        return True
