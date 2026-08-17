# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from odoo.addons.connecta_vas.models.vas_cash_flow_activity import (
    VAS_OP_DEFAULT_CASH_FLOW,
)


class AccountPayment(models.Model):
    _inherit = ['account.payment', 'vas.cash.flow.activity.mixin']

    vas_operation_type = fields.Selection(
        selection=[
            ('employee_advance', 'Tạm ứng nhân viên'),
            ('advance_refund', 'Hoàn tạm ứng (thu lại tiền thừa)'),
            ('employee_debt_payment', 'Trả nợ người lao động'),
            ('internal_transfer', 'Chuyển quỹ nội bộ'),
            ('deposit_out', 'Ký quỹ (mình đưa tiền đi)'),
            ('deposit_in', 'Ký cược (mình nhận tiền của đối tác)'),
            ('import_vat_payment', 'Nộp GTGT hàng NK'),
            # W7 — vay & vốn
            ('loan_receipt', 'Nhận tiền vay'),
            ('loan_repay', 'Trả gốc vay'),
            ('loan_interest_pay', 'Trả lãi vay (qua 335)'),
            ('loan_interest_pay_direct', 'Trả lãi vay thẳng (635)'),
            ('capital_receipt', 'Nhận vốn góp bằng tiền'),
            ('dividend_pay', 'Chi cổ tức / LN cho CSH'),
            ('dividend_tax_pay', 'Nộp TNCN khấu trừ cổ tức'),
            # W9 — lương
            ('payroll_pay', 'Trả lương (334)'),
            ('social_insurance_remit', 'Nộp BHXH/BHYT/BHTN'),
            ('union_fee_remit', 'Nộp kinh phí công đoàn (3382)'),
            ('pit_remit', 'Nộp TNCN (3335)'),
        ],
        string='Nghiệp vụ VAS',
        index=True,
        help='Nhãn nghiệp vụ theo kế toán VN để VAS chọn đúng quy tắc định khoản. '
             'Để trống = giao dịch thường (thu khách / trả NCC).',
    )
    vas_payslip_id = fields.Integer(
        string='ID phiếu lương Odoo',
        index=True,
        copy=False,
        help='Soft-link hr.payslip.id (không M2o — connecta_vas không depends hr_payroll).',
    )
    vas_payroll_remit_account_code = fields.Char(
        string='Mã TK nộp BH (legacy)',
        help='Chỉ dùng khi social_insurance_remit KHÔNG gắn vas_payslip_id: '
             'một TK Nợ đơn (3383/3384/3385). Khi có payslip, adapter tự '
             'tách Nợ 3383+3384+3385 theo dòng phiếu (gộp nộp cơ quan BHXH). '
             'KPCĐ 3382 dùng nhãn riêng union_fee_remit (được nộp từng phần).',
    )
    vas_dest_journal_id = fields.Many2one(
        'account.journal',
        string='Sổ đích nhận tiền',
        domain="[('type', 'in', ('bank', 'cash')), ('company_id', '=', company_id)]",
        help='Sổ quỹ/ngân hàng NHẬN tiền khi chuyển quỹ nội bộ. '
             'Tiền rời khỏi sổ ở trường Nhật ký và vào sổ này.',
    )
    vas_import_vat_id = fields.Many2one(
        'vas.import.vat',
        string='Tờ khai GTGT hàng NK',
        index=True,
        copy=False,
        help='Liên kết tờ khai VAS khi nộp GTGT hàng nhập khẩu (R27 / M11-7).',
    )
    vas_loan_id = fields.Many2one(
        'vas.loan',
        string='Thẻ vay VAS',
        index=True,
        copy=False,
        help='Bắt buộc với nhận vay / trả gốc. Tùy chọn với trả lãi.',
    )

    _LOAN_REQUIRE_LOAN_ID = frozenset({
        'loan_receipt', 'loan_repay',
    })

    @api.onchange('vas_operation_type')
    def _onchange_vas_operation_type(self):
        for payment in self:
            if payment.vas_operation_type != 'internal_transfer':
                payment.vas_dest_journal_id = False
            if payment.vas_operation_type not in (
                'loan_receipt', 'loan_repay',
                'loan_interest_pay', 'loan_interest_pay_direct',
            ):
                payment.vas_loan_id = False
            # Máy điền activity theo bảng 2(a); không nhãn → để trống
            payment.vas_cash_flow_activity = (
                VAS_OP_DEFAULT_CASH_FLOW.get(payment.vas_operation_type) or False
            )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if 'vas_cash_flow_activity' not in vals:
                op = vals.get('vas_operation_type')
                default = VAS_OP_DEFAULT_CASH_FLOW.get(op) if op else False
                if default:
                    vals['vas_cash_flow_activity'] = default
        return super().create(vals_list)

    def write(self, vals):
        # Đường tắt CHỈ khi đúng một khóa vas_cash_flow_activity.
        # Không models.Model.write — vẫn qua AccountPayment.write + context
        # skip sync JE / mail track. Không mở cửa field khác.
        keys = set(vals)
        if keys == {'vas_cash_flow_activity'}:
            return super(AccountPayment, self.with_context(
                skip_account_move_synchronization=True,
                mail_notrack=True,
            )).write(vals)
        # Chặn gộp activity + field khác trên phiếu đã ghi sổ (tránh cửa lách).
        if 'vas_cash_flow_activity' in keys and any(
            p.state != 'draft' for p in self
        ):
            raise ValidationError(_(
                'Chỉ được sửa riêng trường Hoạt động LCTT trên phiếu thanh toán '
                'đã ghi sổ — không gộp với trường khác trong cùng lần ghi.'
            ))
        if 'vas_operation_type' in vals and 'vas_cash_flow_activity' not in vals:
            op = vals.get('vas_operation_type')
            # Chỉ auto-điền khi đổi nhãn; để trống nếu không suy được
            vals = dict(vals)
            vals['vas_cash_flow_activity'] = (
                VAS_OP_DEFAULT_CASH_FLOW.get(op) if op else False
            ) or False
        return super().write(vals)

    @api.constrains('vas_operation_type', 'vas_dest_journal_id', 'journal_id')
    def _check_vas_dest_journal(self):
        for payment in self:
            if payment.vas_operation_type != 'internal_transfer':
                continue
            if not payment.vas_dest_journal_id:
                raise ValidationError(_(
                    'Chuyển quỹ nội bộ bắt buộc chọn Sổ đích nhận tiền.'
                ))
            if payment.vas_dest_journal_id == payment.journal_id:
                raise ValidationError(_(
                    'Sổ đích phải khác Nhật ký nguồn.'
                ))

    @api.constrains('vas_operation_type', 'vas_loan_id')
    def _check_vas_loan_id_required(self):
        for payment in self:
            if payment.vas_operation_type in self._LOAN_REQUIRE_LOAN_ID:
                if not payment.vas_loan_id:
                    raise ValidationError(_(
                        'Nghiệp vụ %(op)s bắt buộc chọn Thẻ vay VAS '
                        '(vas_loan_id) — không để dư nợ trôi.',
                        op=payment.vas_operation_type,
                    ))
