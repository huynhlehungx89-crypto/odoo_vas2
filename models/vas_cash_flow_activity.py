# -*- coding: utf-8 -*-
"""Phân loại hoạt động LCTT trên chứng từ (không gắn vas.move).

Bảng mặc định: docs/nguon/_w11_b03_design.md §2(a).
Ô K / không nhãn → để trống (không mặc định kinh doanh, không đoán theo TK).
"""
from odoo import api, fields, models

VAS_CASH_FLOW_ACTIVITY_SELECTION = [
    ('operating', 'Kinh doanh'),
    ('investing', 'Đầu tư'),
    ('financing', 'Tài chính'),
    ('none', 'Không phải luồng tiền'),
]

# S / N trong bảng 2(a) — máy điền. Không có trong map → để trống (K).
VAS_OP_DEFAULT_CASH_FLOW = {
    'payroll_pay': 'operating',
    'social_insurance_remit': 'operating',
    'union_fee_remit': 'operating',
    'pit_remit': 'operating',
    'loan_interest_pay': 'operating',
    'loan_interest_pay_direct': 'operating',
    'loan_receipt': 'financing',
    'loan_repay': 'financing',
    'capital_receipt': 'financing',
    'dividend_pay': 'financing',
    'dividend_tax_pay': 'financing',
    'employee_advance': 'operating',
    'advance_refund': 'operating',
    'employee_debt_payment': 'operating',
    'deposit_out': 'operating',
    'deposit_in': 'operating',
    'internal_transfer': 'none',
    'import_vat_payment': 'operating',
}


class VasCashFlowActivityMixin(models.AbstractModel):
    _name = 'vas.cash.flow.activity.mixin'
    _description = 'Mixin phân loại hoạt động LCTT'

    vas_cash_flow_activity = fields.Selection(
        selection=VAS_CASH_FLOW_ACTIVITY_SELECTION,
        string='Hoạt động LCTT',
        index=True,
        copy=False,
        help='Phân loại luồng tiền B03: kinh doanh / đầu tư / tài chính / '
             'không phải luồng. Máy điền theo nhãn nghiệp vụ khi suy được; '
             'không suy được thì để trống — không mặc định kinh doanh. '
             'Không gắn lên bút toán VAS.',
    )

    @api.model
    def _vas_default_cash_flow_activity(self, operation_type):
        """Trả activity mặc định hoặc False nếu không suy được (K)."""
        if not operation_type:
            return False
        return VAS_OP_DEFAULT_CASH_FLOW.get(operation_type) or False

    def _vas_apply_default_cash_flow_activity(self, force=False):
        """Điền activity từ vas_operation_type khi trống (hoặc force)."""
        for rec in self:
            op = getattr(rec, 'vas_operation_type', False)
            default = self._vas_default_cash_flow_activity(op)
            if force or not rec.vas_cash_flow_activity:
                if default:
                    rec.vas_cash_flow_activity = default
                elif force:
                    rec.vas_cash_flow_activity = False
