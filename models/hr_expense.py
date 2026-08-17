# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class HrExpense(models.Model):
    _inherit = 'hr.expense'

    vas_advance_payment_id = fields.Many2one(
        'account.payment',
        string='Tạm ứng gốc',
        index=True,
        ondelete='restrict',
        copy=False,
        domain="[('vas_operation_type', '=', 'employee_advance'),"
               " ('company_id', '=', company_id),"
               " ('state', 'in', ('in_process', 'paid'))]",
        help='Phiếu chi tạm ứng mà khoản chi này quyết toán.\n\n'
             'TRƯỜNG BẢN LỀ: có nó thì VAS ghi Có 141 (tất toán tạm ứng); '
             'để trống thì VAS ghi Có 334 (công ty nợ người lao động vì họ tự '
             'bỏ tiền túi). Chọn sai thì khoản tạm ứng treo mãi không tất toán.',
    )
    vas_advance_residual = fields.Monetary(
        string='Tạm ứng còn lại',
        compute='_compute_vas_advance_split',
        currency_field='company_currency_id',
        help='Số dư Nợ 141 còn lại của phiếu tạm ứng gốc, chưa tính khoản chi này.',
    )
    vas_advance_excess = fields.Monetary(
        string='Phần vượt tạm ứng',
        compute='_compute_vas_advance_split',
        currency_field='company_currency_id',
        help='Phần chi vượt quá số tạm ứng còn lại — VAS ghi Có 334 (công ty nợ '
             'người lao động), tất toán bằng phiếu chi gắn nhãn '
             '"Trả nợ người lao động".',
    )

    @api.depends('vas_advance_payment_id', 'total_amount', 'date', 'state')
    def _compute_vas_advance_split(self):
        """Xem trước cách engine sẽ chia — dùng đúng hàm engine dùng, không tính lại.

        Hai chỗ tính hai kiểu là nguồn của lệch số giữa màn hình và sổ.
        """
        Sync = self.env['vas.sync']
        for expense in self:
            if not expense.vas_advance_payment_id:
                expense.vas_advance_residual = 0.0
                expense.vas_advance_excess = 0.0
                continue
            split = Sync._advance_split(expense._origin or expense)
            expense.vas_advance_residual = split['remaining']
            expense.vas_advance_excess = split['advance_excess']

    @api.constrains('vas_advance_payment_id', 'employee_id')
    def _check_advance_employee(self):
        """Tạm ứng của người này không được dùng để quyết toán chi của người khác.

        Workbook T03 ghi rõ "Không chuyển tạm ứng giữa các cá nhân"; 141 theo dõi
        chi tiết từng người nhận nên ghép lệch người sẽ làm 141 của cả hai đều sai.
        """
        for expense in self:
            payment = expense.vas_advance_payment_id
            if not payment or not expense.employee_id:
                continue
            partners = (
                expense.employee_id.work_contact_id
                | expense.employee_id.user_id.partner_id
            )
            if payment.partner_id and payment.partner_id not in partners:
                raise ValidationError(_(
                    "Khoản chi của %(emp)s không thể quyết toán bằng phiếu tạm ứng "
                    "%(pay)s đứng tên %(who)s. TK 141 theo dõi chi tiết từng người "
                    "nhận, không chuyển tạm ứng giữa các cá nhân (workbook T03).",
                    emp=expense.employee_id.display_name,
                    pay=payment.display_name,
                    who=payment.partner_id.display_name,
                ))
