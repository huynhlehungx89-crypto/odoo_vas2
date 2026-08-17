# -*- coding: utf-8 -*-
"""Sổ chi tiết một tài khoản — mẫu S19-DNN / S12-DNN (TT133)."""
import base64
import io
from collections import defaultdict

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare, float_is_zero, float_round

from .vas_books_mixin import PARTNER_ALL

# Mẫu số theo TT133 / DNN (DNN = doanh nghiệp nhỏ & vừa, TT133).
FORM_REGULAR = 'S19-DNN'
FORM_AR_AP = 'S12-DNN'
AR_AP_PREFIXES = ('131', '331')

LEDGER_COLUMNS_S19 = [
    {'name': 'date', 'label': 'Ngày ghi sổ', 'type': 'date', 'align': 'left'},
    {'name': 'move_name', 'label': 'Số chứng từ', 'type': 'string', 'align': 'left'},
    {'name': 'move_date', 'label': 'Ngày chứng từ', 'type': 'date', 'align': 'left'},
    {'name': 'narration', 'label': 'Diễn giải', 'type': 'string', 'align': 'left'},
    {'name': 'counterpart_code', 'label': 'TK đối ứng', 'type': 'string', 'align': 'left'},
    {'name': 'debit', 'label': 'PS Nợ', 'type': 'monetary', 'align': 'right'},
    {'name': 'credit', 'label': 'PS Có', 'type': 'monetary', 'align': 'right'},
    {'name': 'balance_debit', 'label': 'SD Nợ', 'type': 'monetary', 'align': 'right'},
    {'name': 'balance_credit', 'label': 'SD Có', 'type': 'monetary', 'align': 'right'},
    {'name': 'pos_session_name', 'label': 'Phiên quầy', 'type': 'string', 'align': 'left'},
]
LEDGER_COLUMNS_S12 = [
    {'name': 'date', 'label': 'Ngày ghi sổ', 'type': 'date', 'align': 'left'},
    {'name': 'move_name', 'label': 'Số chứng từ', 'type': 'string', 'align': 'left'},
    {'name': 'move_date', 'label': 'Ngày chứng từ', 'type': 'date', 'align': 'left'},
    {'name': 'narration', 'label': 'Diễn giải', 'type': 'string', 'align': 'left'},
    {'name': 'discount_deadline', 'label': 'Thời hạn chiết khấu', 'type': 'date', 'align': 'left'},
    {'name': 'counterpart_code', 'label': 'TK đối ứng', 'type': 'string', 'align': 'left'},
    {'name': 'debit', 'label': 'PS Nợ', 'type': 'monetary', 'align': 'right'},
    {'name': 'credit', 'label': 'PS Có', 'type': 'monetary', 'align': 'right'},
    {'name': 'balance_debit', 'label': 'SD Nợ', 'type': 'monetary', 'align': 'right'},
    {'name': 'balance_credit', 'label': 'SD Có', 'type': 'monetary', 'align': 'right'},
    {'name': 'pos_session_name', 'label': 'Phiên quầy', 'type': 'string', 'align': 'left'},
]


class VasAccountLedgerWizard(models.TransientModel):
    _name = 'vas.account.ledger.wizard'
    _inherit = ['vas.books.mixin']
    _description = 'Sổ chi tiết tài khoản VAS'

    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
    )
    account_id = fields.Many2one(
        'vas.account', string='Tài khoản', required=True, ondelete='cascade',
        domain="[('regime_id', '=', regime_id), ('active', '=', True)]",
    )
    regime_id = fields.Many2one(
        related='company_id.vas_regime_id', store=True,
    )
    period_from_id = fields.Many2one(
        'vas.period', string='Từ kỳ', required=True, ondelete='cascade',
    )
    period_to_id = fields.Many2one(
        'vas.period', string='Đến kỳ', required=True, ondelete='cascade',
    )
    hide_reversed = fields.Boolean(
        string='Ẩn đã đảo/điều chỉnh',
        default=True,
        help='Dùng vas.move.domain_for_amounts (cùng nghĩa ẩn đảo với list). '
             'Số dư không đổi giữa hai chế độ vì cặp đảo triệt tiêu.',
    )
    partner_id = fields.Many2one(
        'res.partner', string='Đối tượng',
        help='Chỉ dùng khi xem một đối tượng (công nợ). Để trống = mọi đối tượng.',
    )
    pos_session_res_id = fields.Integer(
        string='Phiên quầy (id)',
        help='Lọc dòng bút toán theo pos_session_res_id. 0 = mọi phiên. '
             'Dùng cho 1381/3381 lệch két — không tạo đối tác theo phiên.',
    )
    layout = fields.Selection([
        ('regular', 'S19-DNN — Sổ chi tiết các tài khoản'),
        ('ar_ap', 'S12-DNN — Sổ chi tiết thanh toán với người mua/bán'),
    ], string='Mẫu sổ', compute='_compute_layout', store=True)
    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.ref('base.VND'), required=True,
    )
    line_ids = fields.One2many(
        'vas.account.ledger.line', 'wizard_id', string='Dòng sổ', readonly=True,
    )
    form_code = fields.Char(compute='_compute_layout', store=True)
    date_from = fields.Date(related='period_from_id.date_start')
    date_to = fields.Date(related='period_to_id.date_end')

    @api.depends('account_id', 'account_id.code')
    def _compute_layout(self):
        for wiz in self:
            if wiz.account_id and self._is_ar_ap_account(wiz.account_id):
                wiz.layout = 'ar_ap'
                wiz.form_code = FORM_AR_AP
            else:
                wiz.layout = 'regular'
                wiz.form_code = FORM_REGULAR

    @api.model
    def _is_ar_ap_account(self, account):
        code = (account.code or '')
        return any(code.startswith(p) for p in AR_AP_PREFIXES)

    def _check_periods(self):
        self.ensure_one()
        if not self.company_id.vas_regime_id:
            raise UserError(_('Công ty chưa chọn chế độ kế toán VAS.'))
        if self.period_from_id.date_start > self.period_to_id.date_end:
            raise UserError(_('Từ kỳ phải trước hoặc bằng Đến kỳ.'))
        for p in (self.period_from_id, self.period_to_id):
            if p.fiscalyear_id.company_id != self.company_id:
                raise UserError(_('Kỳ %(p)s không thuộc công ty đang chọn.', p=p.display_name))

    def _move_base_domain(self):
        """Domain move dùng chung — hide_reversed → domain_for_amounts."""
        self.ensure_one()
        VasMove = self.env['vas.move']
        domain = [('company_id', '=', self.company_id.id)]
        if self.hide_reversed:
            domain += VasMove.domain_for_amounts()
        else:
            domain.append(('state', 'in', ('posted', 'reversed')))
        return domain

    def _line_domain_account(self, extra=None):
        self.ensure_one()
        extra = list(extra or []) + self._session_domain()
        return self._books_line_domain(
            self.company_id, self.account_id, self.hide_reversed, extra=extra,
        )

    def _session_domain(self):
        self.ensure_one()
        if self.pos_session_res_id:
            return [('pos_session_res_id', '=', self.pos_session_res_id)]
        return []

    def _opening_balance(self, partner=PARTNER_ALL):
        self.ensure_one()
        return self._books_opening_balance(
            self.company_id, self.account_id, self.date_from, self.date_to,
            self.hide_reversed, partner=partner, extra=self._session_domain(),
        )

    def _period_moves(self, partner=PARTNER_ALL):
        """Bút toán phát sinh trong khoảng — LOẠI move_kind=opening."""
        self.ensure_one()
        domain = self._move_base_domain() + [
            ('date', '>=', self.date_from),
            ('date', '<=', self.date_to),
            ('move_kind', '!=', 'opening'),
            ('line_ids.account_id', '=', self.account_id.id),
        ]
        moves = self.env['vas.move'].search(domain, order='date asc, name asc, id asc')
        if partner is PARTNER_ALL and not self.pos_session_res_id:
            return moves
        kept = self.env['vas.move']
        sid = self.pos_session_res_id
        for move in moves:
            target = move.line_ids.filtered(lambda l, acc=self.account_id: l.account_id == acc)
            if sid:
                target = target.filtered(lambda l: l.pos_session_res_id == sid)
            if partner is not PARTNER_ALL:
                if partner:
                    if not any(l.partner_id == partner for l in target):
                        continue
                else:
                    if not any(not l.partner_id for l in target):
                        continue
            if target:
                kept |= move
        return kept

    def _split_counterparts(self, move, partner=PARTNER_ALL):
        """Tách dòng con theo từng TK đối ứng. Dừng nếu TK đích có chân cả hai vế."""
        self.ensure_one()
        account = self.account_id
        target = move.line_ids.filtered(lambda l: l.account_id == account)
        if partner is not PARTNER_ALL:
            if partner:
                target = target.filtered(lambda l: l.partner_id == partner)
            else:
                target = target.filtered(lambda l: not l.partner_id)
        if self.pos_session_res_id:
            target = target.filtered(
                lambda l: l.pos_session_res_id == self.pos_session_res_id
            )
        if not target:
            return []

        has_dr = any(not float_is_zero(l.debit, 2) for l in target)
        has_cr = any(not float_is_zero(l.credit, 2) for l in target)
        if has_dr and has_cr:
            raise UserError(_(
                'Bút toán %(move)s: tài khoản %(code)s có chân ở CẢ HAI vế Nợ/Có. '
                'Không tách đối ứng được duy nhất — dừng, không đoán.',
                move=move.name or move.id,
                code=account.code,
            ))

        narration = move.ref or target[:1].name or ''
        partner_id = target[:1].partner_id.id if target[:1].partner_id else False
        session_name = target[:1].pos_session_name or ''
        session_res_id = target[:1].pos_session_res_id or 0

        if has_dr:
            amount_x = float_round(sum(target.mapped('debit')), precision_digits=2)
            opposite = move.line_ids.filtered(
                lambda l: not float_is_zero(l.credit, 2)
            )
            if not opposite:
                raise UserError(_(
                    'Bút toán %(move)s: TK %(code)s bên Nợ nhưng không có vế Có đối ứng.',
                    move=move.name, code=account.code,
                ))
            opp_total = float_round(sum(opposite.mapped('credit')), precision_digits=2)
            if float_is_zero(opp_total, 2):
                raise UserError(_('Bút toán %s: tổng vế Có = 0.', move.name))
            rows = []
            allocated = 0.0
            opps = list(opposite.sorted(lambda l: (l.account_id.code or '', l.id)))
            for i, opp in enumerate(opps):
                if i == len(opps) - 1:
                    share = float_round(amount_x - allocated, precision_digits=2)
                else:
                    share = float_round(amount_x * (opp.credit / opp_total), precision_digits=2)
                    allocated = float_round(allocated + share, precision_digits=2)
                rows.append({
                    'date': move.date,
                    'move_name': move.name,
                    'move_date': move.date,
                    'narration': narration,
                    'counterpart_code': opp.account_id.code,
                    'counterpart_id': opp.account_id.id,
                    'debit': share,
                    'credit': 0.0,
                    'partner_id': partner_id,
                    'pos_session_name': session_name,
                    'pos_session_res_id': session_res_id,
                    'move_id': move.id,
                })
            return rows

        # Target bên Có
        amount_x = float_round(sum(target.mapped('credit')), precision_digits=2)
        opposite = move.line_ids.filtered(lambda l: not float_is_zero(l.debit, 2))
        if not opposite:
            raise UserError(_(
                'Bút toán %(move)s: TK %(code)s bên Có nhưng không có vế Nợ đối ứng.',
                move=move.name, code=account.code,
            ))
        opp_total = float_round(sum(opposite.mapped('debit')), precision_digits=2)
        if float_is_zero(opp_total, 2):
            raise UserError(_('Bút toán %s: tổng vế Nợ = 0.', move.name))
        rows = []
        allocated = 0.0
        opps = list(opposite.sorted(lambda l: (l.account_id.code or '', l.id)))
        for i, opp in enumerate(opps):
            if i == len(opps) - 1:
                share = float_round(amount_x - allocated, precision_digits=2)
            else:
                share = float_round(amount_x * (opp.debit / opp_total), precision_digits=2)
                allocated = float_round(allocated + share, precision_digits=2)
            rows.append({
                'date': move.date,
                'move_name': move.name,
                'move_date': move.date,
                'narration': narration,
                'counterpart_code': opp.account_id.code,
                'counterpart_id': opp.account_id.id,
                'debit': 0.0,
                'credit': share,
                'partner_id': partner_id,
                'pos_session_name': session_name,
                'pos_session_res_id': session_res_id,
                'move_id': move.id,
            })
        return rows

    def _balance_cols(self, balance):
        return self._books_balance_cols(balance)

    def _build_book_rows(self, partner=PARTNER_ALL):
        """Danh sách dict dòng cho một sổ (một TK, hoặc một TK+đối tượng)."""
        self.ensure_one()
        opening = self._opening_balance(partner=partner)
        sd_dr, sd_cr = self._balance_cols(opening)
        partner_id = False
        if partner is not PARTNER_ALL and partner:
            partner_id = partner.id
        rows = [{
            'row_type': 'opening',
            'date': self.date_from,
            'move_name': '',
            'move_date': False,
            'narration': _('Số dư đầu kỳ'),
            'counterpart_code': '',
            'counterpart_id': False,
            'discount_deadline': False,
            'debit': 0.0,
            'credit': 0.0,
            'balance_debit': sd_dr,
            'balance_credit': sd_cr,
            'partner_id': partner_id,
            'pos_session_name': '',
            'pos_session_res_id': 0,
            'move_id': False,
            'sequence': 10,
        }]

        bal = opening
        seq = 20
        ps_debit = 0.0
        ps_credit = 0.0
        for move in self._period_moves(partner=partner):
            for part in self._split_counterparts(move, partner=partner):
                bal = float_round(bal + part['debit'] - part['credit'], precision_digits=2)
                b_dr, b_cr = self._balance_cols(bal)
                ps_debit = float_round(ps_debit + part['debit'], precision_digits=2)
                ps_credit = float_round(ps_credit + part['credit'], precision_digits=2)
                rows.append({
                    'row_type': 'move',
                    'date': part['date'],
                    'move_name': part['move_name'],
                    'move_date': part['move_date'],
                    'narration': part['narration'],
                    'counterpart_code': part['counterpart_code'],
                    'counterpart_id': part['counterpart_id'],
                    'discount_deadline': False,
                    'debit': part['debit'],
                    'credit': part['credit'],
                    'balance_debit': b_dr,
                    'balance_credit': b_cr,
                    'partner_id': part['partner_id'],
                    'pos_session_name': part.get('pos_session_name') or '',
                    'pos_session_res_id': part.get('pos_session_res_id') or 0,
                    'move_id': part['move_id'],
                    'sequence': seq,
                })
                seq += 10

        b_dr, b_cr = self._balance_cols(bal)
        rows.append({
            'row_type': 'total_ps',
            'date': False,
            'move_name': '',
            'move_date': False,
            'narration': _('Cộng số phát sinh'),
            'counterpart_code': '',
            'counterpart_id': False,
            'discount_deadline': False,
            'debit': ps_debit,
            'credit': ps_credit,
            'balance_debit': 0.0,
            'balance_credit': 0.0,
            'partner_id': partner_id,
            'pos_session_name': '',
            'pos_session_res_id': 0,
            'move_id': False,
            'sequence': seq,
        })
        seq += 10
        rows.append({
            'row_type': 'closing',
            'date': self.date_to,
            'move_name': '',
            'move_date': False,
            'narration': _('Số dư cuối kỳ'),
            'counterpart_code': '',
            'counterpart_id': False,
            'discount_deadline': False,
            'debit': 0.0,
            'credit': 0.0,
            'balance_debit': b_dr,
            'balance_credit': b_cr,
            'partner_id': partner_id,
            'pos_session_name': '',
            'pos_session_res_id': 0,
            'move_id': False,
            'sequence': seq,
        })
        return rows, opening, bal, ps_debit, ps_credit

    def _partners_for_ar_ap(self):
        """Trả (recordset partners, has_empty_partner)."""
        self.ensure_one()
        if self.partner_id:
            return self.partner_id, False
        domain = self._line_domain_account([
            ('date', '<=', self.date_to),
        ])
        lines = self.env['vas.move.line'].search(domain)
        partners = lines.mapped('partner_id').sorted(lambda p: (p.name or '', p.id))
        has_empty = any(not l.partner_id for l in lines)
        return partners, has_empty

    def action_compute(self):
        """Tính sổ → đổ vào line_ids để xem trên màn hình."""
        self.ensure_one()
        self._check_periods()
        self.line_ids.unlink()
        Line = self.env['vas.account.ledger.line']
        vals_list = []
        book_seq = 0

        def _append_book(partner_arg):
            nonlocal book_seq, vals_list
            book_seq += 1
            rows, _, _, _, _ = self._build_book_rows(partner=partner_arg)
            for row in rows:
                vals_list.append({
                    **{k: v for k, v in row.items() if k != 'counterpart_id'},
                    'wizard_id': self.id,
                    'counterpart_id': row['counterpart_id'] or False,
                    'book_sequence': book_seq,
                    'currency_id': self.currency_id.id,
                })

        if self.layout == 'ar_ap':
            partners, has_empty = self._partners_for_ar_ap()
            if partners:
                for partner in partners:
                    _append_book(partner)
            if has_empty and not self.partner_id:
                _append_book(False)
            if not partners and not has_empty:
                _append_book(False)
        else:
            _append_book(PARTNER_ALL)

        if vals_list:
            Line.create(vals_list)
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_export_xlsx(self):
        self.ensure_one()
        if not self.line_ids:
            self.action_compute()
        content = self._render_xlsx()
        filename = 'So_chi_tiet_%s_%s_%s.xlsx' % (
            self.account_id.code or 'TK',
            self.period_from_id.name or '',
            self.period_to_id.name or '',
        )
        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'datas': base64.b64encode(content),
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'res_model': self._name,
            'res_id': self.id,
        })
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }

    def action_print_pdf(self):
        self.ensure_one()
        if not self.line_ids:
            self.action_compute()
        return self.env.ref('connecta_vas.action_report_vas_account_ledger').report_action(self)

    def _render_xlsx(self):
        try:
            from openpyxl import Workbook
            from openpyxl.styles import Alignment, Font, Border, Side
        except ImportError as err:
            raise UserError(_('Thiếu openpyxl — không xuất Excel được.')) from err

        self.ensure_one()
        wb = Workbook()
        ws = wb.active
        ws.title = 'So chi tiet'

        thin = Border(
            left=Side(style='thin'), right=Side(style='thin'),
            top=Side(style='thin'), bottom=Side(style='thin'),
        )
        bold = Font(bold=True)
        company = self.company_id

        ws['A1'] = company.name or ''
        ws['A2'] = _('Mẫu số: %s', self.form_code)
        if self.layout == 'ar_ap':
            ws['A3'] = _('SỔ CHI TIẾT THANH TOÁN VỚI NGƯỜI MUA (NGƯỜI BÁN)')
        else:
            ws['A3'] = _('SỔ CHI TIẾT CÁC TÀI KHOẢN')
        ws['A3'].font = Font(bold=True, size=14)
        ws['A4'] = _('Tài khoản: %(code)s — %(name)s',
                     code=self.account_id.code, name=self.account_id.name)
        ws['A5'] = _('Niên độ: từ %(a)s đến %(b)s',
                     a=self.period_from_id.name, b=self.period_to_id.name)

        headers_regular = [
            _('Ngày ghi sổ'), _('Số chứng từ'), _('Ngày chứng từ'), _('Diễn giải'),
            _('TK đối ứng'), _('PS Nợ'), _('PS Có'), _('SD Nợ'), _('SD Có'),
            _('Phiên quầy'),
        ]
        headers_arap = [
            _('Ngày ghi sổ'), _('Số chứng từ'), _('Ngày chứng từ'), _('Diễn giải'),
            _('Thời hạn chiết khấu'), _('TK đối ứng'),
            _('PS Nợ'), _('PS Có'), _('SD Nợ'), _('SD Có'),
            _('Phiên quầy'),
        ]
        start_row = 7
        current_book = None
        row_i = start_row

        for line in self.line_ids.sorted(lambda l: (l.book_sequence, l.sequence, l.id)):
            if self.layout == 'ar_ap' and line.book_sequence != current_book:
                current_book = line.book_sequence
                if row_i > start_row:
                    row_i += 1
                partner_name = line.partner_id.display_name if line.partner_id else _('(Không đối tượng)')
                ws.cell(row=row_i, column=1, value=_('Đối tượng: %s', partner_name)).font = bold
                row_i += 1
                headers = headers_arap
                for col, h in enumerate(headers, 1):
                    cell = ws.cell(row=row_i, column=col, value=h)
                    cell.font = bold
                    cell.border = thin
                row_i += 1
            elif self.layout != 'ar_ap' and row_i == start_row:
                for col, h in enumerate(headers_regular, 1):
                    cell = ws.cell(row=row_i, column=col, value=h)
                    cell.font = bold
                    cell.border = thin
                row_i += 1

            if self.layout == 'ar_ap':
                values = [
                    line.date or '',
                    line.move_name or '',
                    line.move_date or '',
                    line.narration or '',
                    '',  # thời hạn chiết khấu — để trống
                    line.counterpart_code or '',
                    line.debit or None,
                    line.credit or None,
                    line.balance_debit or None,
                    line.balance_credit or None,
                    line.pos_session_name or '',
                ]
            else:
                values = [
                    line.date or '',
                    line.move_name or '',
                    line.move_date or '',
                    line.narration or '',
                    line.counterpart_code or '',
                    line.debit or None,
                    line.credit or None,
                    line.balance_debit or None,
                    line.balance_credit or None,
                    line.pos_session_name or '',
                ]
            money_from = 7 if self.layout == 'ar_ap' else 6
            for col, val in enumerate(values, 1):
                cell = ws.cell(row=row_i, column=col)
                if col >= money_from:
                    cell.value = val if val not in (None, '') else None
                    if cell.value is None and line.row_type in ('total_ps', 'opening', 'closing'):
                        cell.value = 0
                else:
                    cell.value = val if val not in (False, None) else ''
                cell.border = thin
                if line.row_type in ('opening', 'total_ps', 'closing'):
                    cell.font = bold
            row_i += 1

        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def get_report_books(self):
        """Dữ liệu cho QWeb PDF: list book dicts."""
        self.ensure_one()
        if not self.line_ids:
            self.action_compute()
        books = defaultdict(list)
        partner_by_book = {}
        for line in self.line_ids.sorted(lambda l: (l.book_sequence, l.sequence, l.id)):
            books[line.book_sequence].append(line)
            if line.book_sequence not in partner_by_book:
                partner_by_book[line.book_sequence] = line.partner_id
        result = []
        for seq in sorted(books):
            result.append({
                'partner': partner_by_book.get(seq),
                'lines': books[seq],
            })
        return result

    # ─── Hợp đồng khung OWL (Pha 2) ───────────────────────────────────────────

    @api.model
    def _wizard_from_options(self, options):
        options = options or {}
        company = self.env['res.company'].browse(
            options.get('company_id') or self.env.company.id
        )
        period_from = self.env['vas.period'].browse(options.get('period_from_id'))
        period_to = self.env['vas.period'].browse(options.get('period_to_id'))
        account = self.env['vas.account'].browse(options.get('account_id'))
        if not period_from or not period_to:
            raise UserError(_('Chọn Từ kỳ và Đến kỳ trước khi xem báo cáo.'))
        if not account:
            raise UserError(_('Chọn Tài khoản trước khi xem sổ chi tiết.'))
        partner_id = options.get('partner_id') or False
        return self.create({
            'company_id': company.id,
            'period_from_id': period_from.id,
            'period_to_id': period_to.id,
            'account_id': account.id,
            'hide_reversed': bool(options.get('hide_reversed', True)),
            'partner_id': partner_id,
            'pos_session_res_id': options.get('pos_session_res_id') or 0,
        })

    def _row_to_values(self, row, layout):
        """Map dict dòng sổ → values[] theo columns S19/S12."""
        date_s = fields.Date.to_string(row['date']) if row.get('date') else ''
        move_date_s = fields.Date.to_string(row['move_date']) if row.get('move_date') else ''
        if layout == 'ar_ap':
            return [
                date_s,
                row.get('move_name') or '',
                move_date_s,
                row.get('narration') or '',
                '',  # thời hạn chiết khấu — trống như bản cũ
                row.get('counterpart_code') or '',
                row.get('debit') or 0.0,
                row.get('credit') or 0.0,
                row.get('balance_debit') or 0.0,
                row.get('balance_credit') or 0.0,
                row.get('pos_session_name') or '',
            ]
        return [
            date_s,
            row.get('move_name') or '',
            move_date_s,
            row.get('narration') or '',
            row.get('counterpart_code') or '',
            row.get('debit') or 0.0,
            row.get('credit') or 0.0,
            row.get('balance_debit') or 0.0,
            row.get('balance_credit') or 0.0,
            row.get('pos_session_name') or '',
        ]

    def _book_lines_for_contract(self, partner_arg, book_key, parent_id, level, layout):
        """Chi tiết một sổ: header xổ ra opening/move/total_ps/closing."""
        rows, opening, closing, ps_debit, ps_credit = self._build_book_rows(partner=partner_arg)
        od, oc = self._balance_cols(opening)
        cd, cc = self._balance_cols(closing)
        header_id = f'book_{book_key}'
        if partner_arg is PARTNER_ALL:
            header_label = _('Tài khoản %(code)s — %(name)s',
                             code=self.account_id.code, name=self.account_id.name)
        elif partner_arg:
            header_label = _('Đối tượng: %s', partner_arg.display_name)
        else:
            header_label = _('Đối tượng: (Không đối tượng)')

        if layout == 'ar_ap':
            header_values = [
                '', '', '', header_label, '', '',
                ps_debit, ps_credit, cd, cc,
                '',
            ]
        else:
            header_values = [
                '', '', '', header_label, '',
                ps_debit, ps_credit, cd, cc,
                '',
            ]

        lines = [{
            'id': header_id,
            'label': header_label,
            'level': level,
            'values': header_values,
            'unfoldable': True,
            'unfolded': False,
            'parent_id': parent_id or False,
            'is_total': False,
            'is_leaf': False,
            'is_section': True,
            'class': 'o_vas_section',
        }]
        for idx, row in enumerate(rows):
            is_sum = row['row_type'] in ('opening', 'total_ps', 'closing')
            lines.append({
                'id': f'{header_id}_{row["row_type"]}_{idx}',
                'label': row.get('narration') or '',
                'level': level + 1,
                'values': self._row_to_values(row, layout),
                'unfoldable': False,
                'unfolded': False,
                'parent_id': header_id,
                'is_total': is_sum,
                'is_leaf': row['row_type'] == 'move',
                'class': 'o_vas_report_total' if is_sum else '',
            })
        return lines, {
            'opening_debit': od, 'opening_credit': oc,
            'ps_debit': ps_debit, 'ps_credit': ps_credit,
            'closing_debit': cd, 'closing_credit': cc,
        }

    def _active_child_accounts(self):
        """Con trực tiếp có số dư/PS trong phạm vi kỳ (không đụng child_ids inverse)."""
        self.ensure_one()
        children = self.env['vas.account'].search([
            ('parent_id', '=', self.account_id.id),
            ('regime_id', '=', self.regime_id.id),
            ('active', '=', True),
        ], order='code, id')
        active = self.env['vas.account']
        for child in children:
            child_wiz = self.create({
                'company_id': self.company_id.id,
                'account_id': child.id,
                'period_from_id': self.period_from_id.id,
                'period_to_id': self.period_to_id.id,
                'hide_reversed': self.hide_reversed,
                'currency_id': self.currency_id.id,
            })
            _rows, opening, closing, ps_d, ps_c = child_wiz._build_book_rows(partner=PARTNER_ALL)
            if not all(float_is_zero(x, 2) for x in (opening, closing, ps_d, ps_c)):
                active |= child
        return active

    @api.model
    def get_report_data(self, options):
        """Hợp đồng khung OWL — S19/S12; số y hệt action_compute trên cùng TK."""
        wiz = self._wizard_from_options(options)
        wiz._check_periods()
        layout = wiz.layout
        columns = [
            dict(c) for c in (LEDGER_COLUMNS_S12 if layout == 'ar_ap' else LEDGER_COLUMNS_S19)
        ]
        lines = []
        book_seq = 0
        active_children = wiz._active_child_accounts() if layout != 'ar_ap' else self.env['vas.account']

        if active_children:
            parent_id = f'acc_{wiz.account_id.id}'
            tot_pd = tot_pc = tot_cd = tot_cc = 0.0
            child_blocks = []
            for child in active_children:
                book_seq += 1
                child_wiz = self.create({
                    'company_id': wiz.company_id.id,
                    'account_id': child.id,
                    'period_from_id': wiz.period_from_id.id,
                    'period_to_id': wiz.period_to_id.id,
                    'hide_reversed': wiz.hide_reversed,
                    'currency_id': wiz.currency_id.id,
                })
                block, sums = child_wiz._book_lines_for_contract(
                    PARTNER_ALL, f'{book_seq}_{child.id}', parent_id, 1, child_wiz.layout,
                )
                child_blocks.extend(block)
                tot_pd = float_round(tot_pd + sums['ps_debit'], 2)
                tot_pc = float_round(tot_pc + sums['ps_credit'], 2)
                tot_cd = float_round(tot_cd + sums['closing_debit'], 2)
                tot_cc = float_round(tot_cc + sums['closing_credit'], 2)

            parent_label = _('Tài khoản %(code)s — %(name)s',
                             code=wiz.account_id.code, name=wiz.account_id.name)
            lines.append({
                'id': parent_id,
                'label': parent_label,
                'level': 0,
                'values': [
                    '', '', '', parent_label, '',
                    tot_pd, tot_pc, tot_cd, tot_cc,
                    '',
                ],
                'unfoldable': True,
                'unfolded': False,
                'parent_id': False,
                'is_total': False,
                'is_leaf': False,
                'is_section': True,
                'class': 'o_vas_section',
            })
            lines.extend(child_blocks)
        elif layout == 'ar_ap':
            partners, has_empty = wiz._partners_for_ar_ap()
            targets = []
            if partners:
                targets.extend(list(partners))
            if has_empty and not wiz.partner_id:
                targets.append(False)
            if not targets:
                targets = [False]
            for partner in targets:
                book_seq += 1
                block, _sums = wiz._book_lines_for_contract(
                    partner if partner is not False else False,
                    book_seq,
                    False,
                    0,
                    layout,
                )
                lines.extend(block)
        else:
            book_seq += 1
            block, _sums = wiz._book_lines_for_contract(
                PARTNER_ALL, book_seq, False, 0, layout,
            )
            lines.extend(block)

        title = (
            _('SỔ CHI TIẾT THANH TOÁN VỚI NGƯỜI MUA (NGƯỜI BÁN)')
            if layout == 'ar_ap'
            else _('SỔ CHI TIẾT CÁC TÀI KHOẢN')
        )
        return {
            'meta': {
                'title': title,
                'form_code': wiz.form_code,
                'company_name': wiz.company_id.name or '',
                'period_label': _('Niên độ: từ %(a)s đến %(b)s',
                                  a=wiz.period_from_id.name, b=wiz.period_to_id.name),
                'account_label': _('Tài khoản: %(code)s — %(name)s',
                                   code=wiz.account_id.code, name=wiz.account_id.name),
                'currency_id': wiz.currency_id.id,
                'warning': False,
                'requires_account': True,
            },
            'columns': columns,
            'lines': lines,
            'options': {
                'company_id': wiz.company_id.id,
                'period_from_id': wiz.period_from_id.id,
                'period_to_id': wiz.period_to_id.id,
                'account_id': wiz.account_id.id,
                'partner_id': wiz.partner_id.id if wiz.partner_id else False,
                'pos_session_res_id': wiz.pos_session_res_id or 0,
                'hide_reversed': wiz.hide_reversed,
            },
            'checks': {},
            'wizard_id': wiz.id,
        }

    @api.model
    def action_export_xlsx_options(self, options):
        data = self.get_report_data(options)
        wiz = self.browse(data['wizard_id'])
        wiz.action_compute()
        filename = 'So_chi_tiet_%s_%s_%s.xlsx' % (
            wiz.account_id.code or 'TK',
            wiz.period_from_id.name or '',
            wiz.period_to_id.name or '',
        )
        return self.env['vas.report.engine'].action_download_xlsx(data, filename)

    @api.model
    def action_export_pdf_options(self, options):
        data = self.get_report_data(options)
        wiz = self.browse(data['wizard_id'])
        wiz.action_compute()
        return self.env.ref('connecta_vas.action_report_vas_account_ledger').report_action(wiz)


class VasAccountLedgerLine(models.TransientModel):
    _name = 'vas.account.ledger.line'
    _description = 'Dòng sổ chi tiết tài khoản VAS'
    _order = 'book_sequence, sequence, id'

    wizard_id = fields.Many2one(
        'vas.account.ledger.wizard', required=True, ondelete='cascade',
    )
    book_sequence = fields.Integer(default=1)
    sequence = fields.Integer(default=10)
    row_type = fields.Selection([
        ('opening', 'Số dư đầu kỳ'),
        ('move', 'Phát sinh'),
        ('total_ps', 'Cộng phát sinh'),
        ('closing', 'Số dư cuối kỳ'),
    ], required=True)
    date = fields.Date(string='Ngày ghi sổ')
    move_id = fields.Many2one('vas.move', string='Bút toán')
    move_name = fields.Char(string='Số chứng từ')
    move_date = fields.Date(string='Ngày chứng từ')
    narration = fields.Char(string='Diễn giải')
    counterpart_id = fields.Many2one('vas.account', string='TK đối ứng')
    counterpart_code = fields.Char(string='Mã TK đối ứng')
    discount_deadline = fields.Date(string='Thời hạn chiết khấu')
    partner_id = fields.Many2one('res.partner', string='Đối tượng')
    pos_session_name = fields.Char(string='Phiên quầy')
    pos_session_res_id = fields.Integer(string='Phiên quầy (id)')
    currency_id = fields.Many2one('res.currency')
    debit = fields.Monetary(string='PS Nợ', currency_field='currency_id')
    credit = fields.Monetary(string='PS Có', currency_field='currency_id')
    balance_debit = fields.Monetary(string='SD Nợ', currency_field='currency_id')
    balance_credit = fields.Monetary(string='SD Có', currency_field='currency_id')
