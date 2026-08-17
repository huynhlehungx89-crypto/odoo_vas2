# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare

CITATION_M11_3 = (
    'M11-3 · Nợ 1331 / Có 33312 · TT133 Điều 18 + Điều 41'
)
CITATION_M11_7 = (
    'M11-7 · Nợ 33312 / Có 111|112 · TT133 Điều 41'
)


class VasImportVat(models.Model):
    """Tờ khai GTGT hàng nhập khẩu (đường B) — VAS tự sở hữu (R22).

    M11-3: xác nhận → Nợ 1331 / Có 33312 (chứng từ sinh vas.move).
    M11-7: nộp qua account.payment nhãn import_vat_payment → R27;
    action «Đã nộp» chỉ link payment + state, KHÔNG tự Có 112.
    """

    _name = 'vas.import.vat'
    _description = 'Tờ khai GTGT hàng nhập khẩu'
    _order = 'date desc, id desc'

    name = fields.Char(
        string='Số phiếu',
        required=True,
        copy=False,
        default='/',
        index=True,
    )
    declaration_number = fields.Char(
        string='Số tờ khai HQ',
        index=True,
        help='Số tờ khai hải quan (tra cứu).',
    )
    date = fields.Date(
        string='Ngày tờ khai',
        required=True,
        index=True,
        default=fields.Date.context_today,
    )
    payment_date = fields.Date(string='Ngày nộp', copy=False)
    partner_id = fields.Many2one(
        'res.partner',
        string='Đối tượng',
        index=True,
        help='HQ / NSNN / đại lý — optional.',
    )
    picking_ids = fields.Many2many(
        'stock.picking',
        'vas_import_vat_picking_rel',
        'import_vat_id',
        'picking_id',
        string='Phiếu nhập',
        help='Liên kết tra cứu — không dùng để định khoản.',
    )
    purchase_id = fields.Many2one(
        'purchase.order',
        string='Đơn mua',
        index=True,
        help='Liên kết tra cứu — optional.',
    )
    amount_vat = fields.Monetary(
        string='GTGT hàng NK',
        required=True,
        currency_field='currency_id',
    )
    amount_paid = fields.Monetary(
        string='Số đã nộp',
        currency_field='currency_id',
        copy=False,
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Tiền tệ',
        required=True,
        default=lambda self: self.env.ref('base.VND'),
    )
    company_id = fields.Many2one(
        'res.company',
        string='Công ty',
        required=True,
        index=True,
        default=lambda self: self.env.company,
    )
    regime_id = fields.Many2one(
        'vas.regime',
        string='Chế độ',
        required=True,
        index=True,
        default=lambda self: self.env.company.vas_regime_id,
    )
    period_id = fields.Many2one(
        'vas.period',
        string='Kỳ',
        compute='_compute_period_id',
        store=True,
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Nháp'),
            ('confirmed', 'Đã xác nhận'),
            ('paid', 'Đã nộp'),
            ('cancelled', 'Đã hủy'),
        ],
        string='Trạng thái',
        default='draft',
        required=True,
        copy=False,
        index=True,
    )
    ref = fields.Char(string='Diễn giải')
    accrual_move_id = fields.Many2one(
        'vas.move',
        string='Bút toán M11-3',
        copy=False,
        readonly=True,
    )
    payment_move_id = fields.Many2one(
        'vas.move',
        string='Bút toán M11-7',
        copy=False,
        readonly=True,
        help='Do R27 sinh từ payment nhãn import_vat_payment — không do nút Đã nộp.',
    )
    payment_id = fields.Many2one(
        'account.payment',
        string='Phiếu chi Odoo',
        copy=False,
        index=True,
        domain="[('company_id', '=', company_id), "
               "('payment_type', '=', 'outbound')]",
        help='Bắt buộc nhãn Nghiệp vụ VAS = Nộp GTGT hàng NK.',
    )
    pending_odoo_payment = fields.Boolean(
        string='Chờ nộp qua Odoo',
        default=False,
        copy=False,
        help='Bật khi chưa có payment đúng nhãn / nộp ngoài Odoo '
             '(chưa xử trong phiên này — không tự chế bút toán).',
    )

    @api.depends('date', 'company_id')
    def _compute_period_id(self):
        Period = self.env['vas.period']
        for rec in self:
            if not rec.date:
                rec.period_id = False
                continue
            domain = [
                ('date_start', '<=', rec.date),
                ('date_end', '>=', rec.date),
            ]
            if rec.company_id:
                domain.append(
                    ('fiscalyear_id.company_id', '=', rec.company_id.id),
                )
            rec.period_id = Period.search(domain, limit=1)

    def action_confirm(self):
        """M11-3: Nợ 1331 / Có 33312 ngay khi xác nhận tờ khai."""
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_("Chỉ tờ khai nháp mới xác nhận được."))
            if float_compare(rec.amount_vat, 0.0, precision_digits=2) <= 0:
                raise UserError(_("Số tiền GTGT hàng NK phải > 0."))
            if rec.accrual_move_id:
                raise UserError(_("Tờ khai đã có bút toán M11-3."))
            move = rec._create_accrual_move()
            name = rec.name
            if name == '/':
                name = f'GTGTNK/{rec.date}/{rec.id}'
            rec.write({
                'state': 'confirmed',
                'accrual_move_id': move.id,
                'name': name,
                'pending_odoo_payment': False,
            })
        return True

    def action_cancel(self):
        """Hủy tờ khai confirmed → cancelled + đảo accrual (Q6/Q7).

        PAID: chặn — hủy khoản nộp trước. Không đảo JE payment (R27).
        Kỳ khóa theo ngày → source_cancel_pending; missing → không đảo.
        """
        Period = self.env['vas.period']
        for rec in self:
            if rec.state == 'paid':
                raise UserError(_(
                    "Hủy khoản nộp trước rồi mới hủy tờ khai."
                ))
            if rec.state != 'confirmed':
                raise UserError(_(
                    "Chỉ tờ khai đã xác nhận (chưa nộp) mới hủy được."
                ))
            move = rec.accrual_move_id
            if move and move.state == 'posted':
                status = Period._coverage_status(move.company_id, move.date)
                if status == 'closed':
                    move.with_context(
                        vas_allow_posted_write=True,
                        vas_skip_period_check=True,
                    ).write({'source_cancel_pending': True})
                elif status == 'missing':
                    Period._raise_missing_period(
                        move.company_id, move.date, doc_name=move.name,
                    )
                else:
                    move.action_reverse()
            rec.write({'state': 'cancelled'})
        return True

    def write(self, vals):
        # Q7: cancelled là chốt — không reset về draft trên cùng id.
        if 'state' in vals and vals['state'] == 'draft':
            locked = self.filtered(lambda r: r.state == 'cancelled')
            if locked:
                raise UserError(_(
                    "Tờ khai đã hủy không mở lại được. Tạo tờ khai mới."
                ))
        return super().write(vals)

    def action_mark_paid(self):
        """Chỉ link payment nhãn import_vat_payment + state=paid.

        KHÔNG sinh Nợ 33312 / Có 112 — R27 làm việc đó khi sync.
        """
        for rec in self:
            if rec.state != 'confirmed':
                raise UserError(_(
                    "Chỉ tờ khai đã xác nhận mới đánh dấu đã nộp được.",
                ))
            payment = rec.payment_id
            if (
                not payment
                or payment.vas_operation_type != 'import_vat_payment'
                or payment.payment_type != 'outbound'
                or payment.state not in ('in_process', 'paid')
            ):
                # State chờ + cờ — không tự chế JE (nộp ngoài Odoo / thiếu nhãn).
                rec.write({'pending_odoo_payment': True})
                continue
            if payment.company_id != rec.company_id:
                raise UserError(_("Phiếu chi phải cùng công ty với tờ khai."))
            pay_move = self.env['vas.move'].search([
                ('source_model', '=', 'account.payment'),
                ('source_res_id', '=', payment.id),
                ('move_kind', '=', 'import_vat_payment'),
                ('state', '=', 'posted'),
                ('is_reversal', '=', False),
            ], limit=1)
            vals = {
                'state': 'paid',
                'pending_odoo_payment': False,
                'payment_date': payment.date,
                'amount_paid': abs(payment.amount or 0.0),
            }
            if pay_move:
                vals['payment_move_id'] = pay_move.id
            if not payment.vas_import_vat_id:
                payment.vas_import_vat_id = rec.id
            rec.write(vals)
        return True

    def _create_accrual_move(self):
        self.ensure_one()
        regime = self.regime_id
        acc_1331 = self.env['vas.account'].search([
            ('regime_id', '=', regime.id),
            ('code', '=', '1331'),
            ('active', '=', True),
        ], limit=1)
        acc_33312 = self.env['vas.account'].search([
            ('regime_id', '=', regime.id),
            ('code', '=', '33312'),
            ('active', '=', True),
        ], limit=1)
        if not acc_1331 or not acc_33312:
            raise UserError(_("Thiếu tài khoản VAS 1331 hoặc 33312."))
        journal = self.env['vas.journal'].search([
            ('company_id', '=', self.company_id.id),
            ('code', '=', 'TH'),
        ], limit=1) or self.env['vas.journal'].search([
            ('company_id', '=', self.company_id.id),
            ('code', '=', 'MH'),
        ], limit=1)
        if not journal:
            raise UserError(_("Thiếu sổ nhật ký VAS TH hoặc MH."))
        amount = self.amount_vat
        partner = self.partner_id
        label = self.ref or CITATION_M11_3
        from odoo import Command
        move = self.env['vas.move'].create({
            'date': self.date,
            'journal_id': journal.id,
            'regime_id': regime.id,
            'move_kind': 'import_vat',
            'ref': CITATION_M11_3,
            'source_model': self._name,
            'source_res_id': self.id,
            'source_ref': self.display_name if self.name != '/' else CITATION_M11_3,
            'company_id': self.company_id.id,
            'currency_id': self.currency_id.id,
            'narration': CITATION_M11_3,
            'line_ids': [
                Command.create({
                    'sequence': 10,
                    'account_id': acc_1331.id,
                    'name': label,
                    'debit': amount,
                    'credit': 0.0,
                    'partner_id': partner.id if partner else False,
                    'currency_id': self.currency_id.id,
                }),
                Command.create({
                    'sequence': 20,
                    'account_id': acc_33312.id,
                    'name': label,
                    'debit': 0.0,
                    'credit': amount,
                    'partner_id': partner.id if partner else False,
                    'currency_id': self.currency_id.id,
                }),
            ],
        })
        move.action_post()
        return move
